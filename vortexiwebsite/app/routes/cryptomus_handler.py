import base64
import hashlib
import requests
import json
import string
import secrets
import logging
import redis_lock

from flask import request, Blueprint, jsonify, make_response, abort, redirect, render_template
from functools import wraps
from datetime import datetime, timedelta
from flask_wtf.csrf import CSRFError
from config import Config

from app.models.cryptomus_invoice import CryptomusInvoice
from app.models.user import User
from app.models.giftcard_key import GiftcardKey
from app.enums.GiftcardType import GiftcardType
from app.enums.CryptomusPaymentStatus import CryptomusPaymentStatus

from app.util import auth
from app.extensions import get_remote_address, db, csrf, user_limiter, redis_controller, limiter

config = Config()

CryptomusHandler = Blueprint('CryptomusHandler', __name__, url_prefix='/cryptomus_service')

StatusStringToEnum = {
    "paid": CryptomusPaymentStatus.Paid,
    "paid_over": CryptomusPaymentStatus.PaidOver,
    "wrong_amount": CryptomusPaymentStatus.WrongAmount,
    "process": CryptomusPaymentStatus.Process,
    "confirm_check": CryptomusPaymentStatus.ConfirmCheck,
    "wrong_amount_waiting": CryptomusPaymentStatus.WrongAmountWaiting,
    "check": CryptomusPaymentStatus.Check,
    "fail": CryptomusPaymentStatus.Fail,
    "cancel": CryptomusPaymentStatus.Cancel,
    "system_fail": CryptomusPaymentStatus.SystemFail,
    "refund_process": CryptomusPaymentStatus.RefundProcess,
    "refund_fail": CryptomusPaymentStatus.RefundFail,
    "refund_paid": CryptomusPaymentStatus.RefundPaid,
    "locked": CryptomusPaymentStatus.Locked
}

def GenerateSignature( PayloadData : str = "" ) -> str:
    """
        Generates a signature for the given payload data

        :param PayloadData: The payload data to sign

        :returns: str
    """
    assert isinstance( PayloadData, str ), "PayloadData must be a string"

    return hashlib.md5(
        (
            base64.b64encode( PayloadData.encode( "utf-8" ) ).decode( "utf-8" ) + config.CRYPTOMUS_API_KEY
        ).encode( "utf-8" )
    ).hexdigest()

def VerifySignature( PayloadData : str, Signature : str ) -> bool:
    """
        Verifies the signature of the given payload data

        :param PayloadData: The payload data to verify
        :param Signature: The signature to verify

        :returns: bool
    """
    assert isinstance( PayloadData, str ), "PayloadData must be a string"
    assert isinstance( Signature, str ), "Signature must be a string"

    return GenerateSignature( PayloadData ) == Signature

def PerformRequest( Endpoint : str = "/", RequestMethod : str = "GET", PayloadData : dict | list | None = None, RequestTimeout : int = 20 ) -> requests.Response:
    """
        Performs a request to the Cryptomus API

        :param Endpoint: The endpoint to send the request to
        :param RequestMethod: The request method to use
        :param PayloadData: The payload data to send with the request on POST requests
        :param RequestTimeout: The amount of time before the request times out

        :returns: requests.Response
    """

    assert isinstance( Endpoint, str ), "Endpoint must be a string"
    assert isinstance( RequestMethod, str ), "RequestMethod must be a string"
    assert RequestMethod in ["GET", "POST"], "RequestMethod must be either GET or POST"
    assert isinstance( PayloadData, (dict, list, type(None)) ), "PayloadData must be a dictionary, list or None"
    assert isinstance( RequestTimeout, int ), "RequestTimeout must be an integer"

    headers = {
        "Content-Type": "application/json",
        "merchant": config.CRYPTOMUS_MERCHANT_ID,
    }

    if RequestMethod == "GET":
        headers.update({
            "sign": GenerateSignature()
        })
        return requests.get(
            url = f"{config.CRYPTOMUS_API_BASEURL}{Endpoint}",
            headers = headers,
            timeout = RequestTimeout
        )
    else:
        headers.update({
            "sign": GenerateSignature( json.dumps( PayloadData ) )
        })
        return requests.post(
            url = f"{config.CRYPTOMUS_API_BASEURL}{Endpoint}",
            headers = headers,
            data = json.dumps( PayloadData ),
            timeout = RequestTimeout
        )
    
def CryptomusSignatureRequired(f):
    """
        Decorator to require a valid Cryptomus signature for a request
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if get_remote_address() != "91.227.144.54":
            logging.warning(f"cryptomus_handler > CryptomusSignatureRequired > Invalid remote address: {get_remote_address()}")
            abort(404)

        if not request.is_json:
            logging.warning(f"cryptomus_handler > CryptomusSignatureRequired > Request is not JSON")
            abort(400)
        PayloadData = request.get_json()
        if "sign" not in PayloadData:
            logging.warning(f"cryptomus_handler > CryptomusSignatureRequired > sign not found in payload")
            abort(400)
        # PayloadSignature = PayloadData["sign"]
        # del PayloadData["sign"]
        # if not VerifySignature( json.dumps( PayloadData ), PayloadSignature ):
        #     logging.warning(f"cryptomus_handler > CryptomusSignatureRequired > Invalid signature")
        #     abort(400)
        
        return f(*args, **kwargs)
    return decorated_function

def GenerateInvoiceID():
    """
        Generates a new invoice ID

        :returns: str
    """
    
    NewInvoiceID = ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(64))

    if CryptomusInvoice.query.filter_by( id = NewInvoiceID ).first() is not None:
        # This will never happen, but we are handling money here so we need to be sure
        return GenerateInvoiceID()
    
    return NewInvoiceID

def ConvertStringStatusToEnum( Status : str ) -> CryptomusPaymentStatus:
    """
        Converts a string status to a CryptomusPaymentStatus enum

        :param Status: The status to convert

        :returns: CryptomusPaymentStatus
    """

    assert Status in StatusStringToEnum, "Invalid status"
    return StatusStringToEnum[Status]

@CryptomusHandler.errorhandler( 429 )
def RateLimitExceeded( e ):
    """
        Rate limit exceeded error handler
    """
    return jsonify({ "status": "error", "message": "Rate limit exceeded" }), 429

@CryptomusHandler.errorhandler( CSRFError )
def CSRFError( e ):
    """
        CSRF error handler
    """
    return jsonify({ "status": "error", "message": "Invalid CSRF Token" }), 400

@CryptomusHandler.route("/invoice_status_callback/<invoice_id>", methods=["POST"])
@CryptomusSignatureRequired
@csrf.exempt
def InvoiceStatusCallback( invoice_id : str ):
    """
        Callback for invoice status updates

        :param invoice_id: The invoice ID to update the status for
    """

    CryptomusInvoiceObj : CryptomusInvoice = CryptomusInvoice.query.filter_by( id = invoice_id ).first()
    if CryptomusInvoiceObj is None:
        logging.warning(f"cryptomus_handler > InvoiceStatusCallback > Invoice not found: {invoice_id}")
        return jsonify({ "status": "error", "message": "Invoice not found" }), 404
    PayloadData = request.get_json()

    try:
        assert isinstance( PayloadData, dict ), "PayloadData must be a dictionary"
        assert "status" in PayloadData, "Status not found in payload"
        assert "payment_amount_usd" in PayloadData, "payment_amount_usd not found in payload"
        assert "is_final" in PayloadData, "is_final not found in payload"
        assert isinstance( PayloadData["payment_amount_usd"], str ), "payment_amount_usd must be a string"
        assert isinstance( PayloadData["is_final"], bool ), "is_final must be a boolean"
        assert PayloadData["status"] in StatusStringToEnum, "Invalid status"
    except Exception as e:
        logging.error(f"cryptomus_handler > InvoiceStatusCallback > Validation failed: {e}")
        return jsonify({ "status": "error", "message": f"Validation failed: {e}" }), 500
    
    CryptomusInvoiceObj.status = StatusStringToEnum[PayloadData["status"]]
    CryptomusInvoiceObj.paid_amount_usd = float(PayloadData["payment_amount_usd"])
    CryptomusInvoiceObj.is_final = PayloadData["is_final"]
    CryptomusInvoiceObj.updated_at = datetime.utcnow()
    db.session.commit()

    def GenerateCode():
        Code = ""
        for i in range(0, 5):
            Chunk = ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(5))
            Code += Chunk
            if i != 4:
                Code += "-"
        return Code

    if CryptomusInvoiceObj.status in [ CryptomusPaymentStatus.Paid, CryptomusPaymentStatus.PaidOver ] and CryptomusInvoiceObj.assigned_key is None and CryptomusInvoiceObj.extra_data == "membership":
        NewGiftcardCode : str = GenerateCode()
        NewGiftcardObj : GiftcardKey = GiftcardKey(
            key = NewGiftcardCode,
            type = GiftcardType.Outrageous_BuildersClub,
            value = 1
        )
        db.session.add(NewGiftcardObj)
        db.session.commit()

        CryptomusInvoiceObj.assigned_key = NewGiftcardObj.key
        db.session.commit()

    return jsonify({ "status": "success" }), 200

@CryptomusHandler.route("/payment_cancelled/<invoice_id>", methods=["GET"])
@auth.authenticated_required
def PaymentCancelled( invoice_id : str ):
    InvoiceObj : CryptomusInvoice = CryptomusInvoice.query.filter_by( id = invoice_id ).first()
    if InvoiceObj is None:
        return abort(404)
    AuthenticatedUser : User = auth.GetCurrentUser()
    if InvoiceObj.initiator_id != AuthenticatedUser.id:
        return abort(404)

    return redirect(f"/cryptomus_service/view_payment/{invoice_id}")

@CryptomusHandler.route("/payment_success/<invoice_id>", methods=["GET"])
@auth.authenticated_required
def PaymentSuccess( invoice_id : str ):
    InvoiceObj : CryptomusInvoice = CryptomusInvoice.query.filter_by( id = invoice_id ).first()
    if InvoiceObj is None:
        return abort(404)
    AuthenticatedUser : User = auth.GetCurrentUser()
    if InvoiceObj.initiator_id != AuthenticatedUser.id:
        return abort(404)

    return redirect(f"/cryptomus_service/view_payment/{invoice_id}")

@CryptomusHandler.route("/create_payment/membership", methods=["POST"])
@auth.authenticated_required_api
@limiter.limit("5/minute")
@user_limiter.limit("5/minute")
def user_create_payment():
    AuthenticatedUser : User = auth.GetCurrentUser()

    try:
        with redis_lock.Lock(
            redis_client = redis_controller,
            name = f"cryptomus_handler:user_create_payment:{AuthenticatedUser.id}",
            expire = 30,
            auto_renewal = True
        ) as lock:
            ActiveUserInvoices : int = CryptomusInvoice.query.filter_by( initiator_id = AuthenticatedUser.id ).filter(
                CryptomusInvoice.created_at > datetime.now() - timedelta( minutes = 30 )
            ).count(
            )
            if ActiveUserInvoices >= 10:
                return jsonify({ "status": "error", "message": "You have created too many payments recently" }), 403
            
            InvoiceOrderID = GenerateInvoiceID()

            try:
                InvoiceCreateRequest = PerformRequest(
                    Endpoint = "/v1/payment",
                    RequestMethod = "POST",
                    PayloadData = {
                        "amount": "5",
                        "currency": "USD",
                        "order_id": InvoiceOrderID,
                        "url_return": f"{config.BaseURL}/cryptomus_service/payment_cancelled/{InvoiceOrderID}",
                        "url_callback": f"{config.BaseURL}/cryptomus_service/invoice_status_callback/{InvoiceOrderID}",
                        "url_success": f"{config.BaseURL}/cryptomus_service/payment_success/{InvoiceOrderID}",
                        "is_payment_multiple": True,
                        "lifetime": 60 * 60 * 12, # 12 hours
                        "additional_data": "membership"
                    }
                )
            except requests.exceptions.RequestException as e:
                logging.error(f"cryptomus_handler > user_create_payment > Request failed: {e}")
                return jsonify({ "status": "error", "message": "Request failed" }), 500
            except Exception as e:
                logging.error(f"cryptomus_handler > user_create_payment > Unknown error: {e}")
                return jsonify({ "status": "error", "message": "Unknown error" }), 500
            
            if InvoiceCreateRequest.status_code != 200:
                logging.error(f"cryptomus_handler > user_create_payment > Request failed: {InvoiceCreateRequest.status_code}, {InvoiceCreateRequest.text}")
                return jsonify({ "status": "error", "message": "Request failed" }), 500
            
            InvoiceCreateResponse = InvoiceCreateRequest.json()
            try:
                assert "state" in InvoiceCreateResponse, "state not found in response"
                assert isinstance( InvoiceCreateResponse["state"], int ), "state must be a integer"
                assert "result" in InvoiceCreateResponse, "result not found in response"
                assert isinstance( InvoiceCreateResponse["result"], dict ), "result must be a dictionary"
            except AssertionError as e:
                logging.error(f"cryptomus_handler > user_create_payment > Validation failed: {e}")
                return jsonify({ "status": "error", "message": f"Request failed" }), 500
            
            if InvoiceCreateResponse["state"] != 0:
                logging.error(f"cryptomus_handler > user_create_payment > Request failed: {InvoiceCreateResponse['result']}")
                return jsonify({ "status": "error", "message": "Request failed" }), 500
            
            InvoiceResult : dict = InvoiceCreateResponse["result"]
            NewCryptomusInvoice = CryptomusInvoice(
                id = InvoiceOrderID,
                cryptomus_invoice_id = InvoiceResult["uuid"],
                initiator_id = AuthenticatedUser.id,
                required_amount = 5,
                currency = "USD",
                status = ConvertStringStatusToEnum( InvoiceResult["status"] ),
                expires_at = datetime.utcnow() + timedelta( hours = 12 ),
                extra_data = "membership"
            )
            db.session.add(NewCryptomusInvoice)
            db.session.commit()

            return jsonify({ "status": "success", "invoice_id": InvoiceOrderID, "cryptomus_invoice_id": InvoiceResult["uuid"], "payment_url": InvoiceResult["url"] }), 200
    except AssertionError:
        abort( 429 )

@CryptomusHandler.route("/pay_invoice/<invoice_id>", methods=["GET"])
@auth.authenticated_required
def pay_invoice( invoice_id : str ):
    AuthenticatedUser : User = auth.GetCurrentUser()
    InvoiceObj : CryptomusInvoice = CryptomusInvoice.query.filter_by( id = invoice_id ).first()
    if InvoiceObj is None:
        return abort(404)
    if InvoiceObj.initiator_id != AuthenticatedUser.id:
        return abort(404)
    
    return redirect( f"https://pay.cryptomus.com/pay/{InvoiceObj.cryptomus_invoice_id}" )

@CryptomusHandler.route("/view_payment/<invoice_id>", methods=["GET"])
@auth.authenticated_required
def view_payment( invoice_id : str ):
    AuthenticatedUser : User = auth.GetCurrentUser()
    InvoiceObj : CryptomusInvoice = CryptomusInvoice.query.filter_by( id = invoice_id ).first()
    if InvoiceObj is None:
        return abort(404)
    if InvoiceObj.initiator_id != AuthenticatedUser.id:
        return abort(404)
    
    return render_template("cryptomus/view_payment.html", InvoiceObj = InvoiceObj)
    
@CryptomusHandler.route("/dashboard", methods=["GET"])
@auth.authenticated_required
def dashboard():
    AuthenticatedUser : User = auth.GetCurrentUser()
    PageNumber = max(request.args.get('page', default=1, type=int) , 1)
    UserInvoices = CryptomusInvoice.query.filter_by( initiator_id = AuthenticatedUser.id ).order_by( CryptomusInvoice.created_at.desc() ).paginate(
        page=PageNumber, per_page=15, error_out=False
    )
    return render_template("cryptomus/dashboard.html", UserInvoices = UserInvoices)

