import base64
import redis
import sys
import os
import hashlib
import traceback
import string
import secrets
import re
import logging
from config import Config
from logging.handlers import TimedRotatingFileHandler
from flask import Flask, jsonify, render_template, session, redirect, url_for, request, make_response, Response
from datetime import datetime, timedelta
from urllib.parse import urlparse

from app.models.user import User
from app.models.messages import Message
from app.models.user_trades import UserTrade
from app.models.friend_request import FriendRequest
from app.models.asset import Asset
from app.models.asset_version import AssetVersion
from app.models.game_session_log import GameSessionLog
from app.enums.TradeStatus import TradeStatus
from app.enums.AssetType import AssetType
from app.enums.TransactionType import TransactionType
from app.util import auth, assetversion, s3helper, signscript, transactions
from app.services.economy import IncrementTargetBalance, GetUserBalance
from app.extensions import db, limiter, scheduler, CORS, redis_controller, csrf, get_remote_address
import app.shell_commands as cmd

logging.basicConfig(
    level = logging.INFO,
    format = "%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)
logname = "./logs/syntaxweb.log"
handler = TimedRotatingFileHandler(logname, when="midnight", backupCount=30)
handler.suffix = "%Y%m%d"

logging.getLogger().addHandler(handler)


TwelveClientAssets = [37801173, 46295864, 48488236, 53870848, 53870858, 60595696, 89449009, 89449094, 97188757]
def create_app(config_class=Config):
    app = Flask(__name__, template_folder="pages")
    app.config.from_object(config_class)
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config["SECRET_KEY"] = config_class.FLASK_SESSION_KEY
    app.config['CORS_HEADERS'] = 'Content-Type'
    app.config['SESSION_TYPE'] = 'redis'
    app.config['SESSION_REDIS'] = redis.from_url(Config.FLASK_LIMITED_STORAGE_URI)
    app.config['MAX_CONTENT_LENGTH'] = 32 * 1024 * 1024
    app.config["SQUEEZE_MIN_SIZE"] = 0
    #if app.debug is False:
        #app.config["SERVER_NAME"] = config_class.BaseDomain

    db.init_app(app)
    limiter.init_app(app)
    csrf.init_app(app)
    clean_domain = config_class.BaseDomain.replace('.', r'\.')
    CORS.init_app(app, supports_credentials=True, resources={r"/*": {"origins": [f"https://{clean_domain}", f"http://{clean_domain}", f"https://.+{clean_domain}", f"http://.+{clean_domain}"]}})
    scheduler.init_app(app)
    scheduler.start()

    from app.pages.login.login import login
    from app.pages.signup.signup import signup
    from app.pages.static import static
    from app.pages.settings.settings import settings
    from app.pages.home.home import home
    from app.pages.admin.admin import AdminRoute, GetAmountOfPendingAssets, IsUserAnAdministrator
    from app.routes.asset import AssetRoute
    from app.routes.authentication import AuthenticationRoute
    from app.routes.jobreporthandler import JobReportHandler
    from app.routes.clientinfo import ClientInfo
    from app.routes.thumbnailer import Thumbnailer
    from app.routes.image import ImageRoute
    from app.routes.fflagssettings import FFlagRoute
    from app.pages.profiles.profile import Profile
    from app.routes.gamejoin import GameJoinRoute
    from app.routes.marketplace import MarketPlaceRoute, EconomyV1Route
    from app.routes.presence import PresenceRoute
    from app.pages.messages.messages import MessageRoute
    #from app.pages.clothingmigrator.migrator import ClothingMigratorRoute
    from app.pages.catalog.catalog import CatalogRoute
    from app.pages.avatar.avatar import AvatarRoute
    from app.routes.pointsservice import PointsServiceRoute
    from app.routes.datastoreservice import DataStoreRoute
    from app.pages.clientpages.clientpages import ClientPages
    from app.routes.luawebservice import LuaWebServiceRoute
    from app.pages.develop.develop import DevelopPagesRoute
    from app.routes.bootstrapper import BootstrapperRoute
    from app.pages.studio.studiopages import StudioPagesRoute
    from app.pages.games.games import GamePagesRoute
    from app.pages.membership.membership import MembershipPages
    from app.routes.rate import AssetRateRoute
    from app.pages.trades.trades import TradesPageRoute
    from app.routes.sets import SetsRoute
    from app.pages.notapproved.notapproved import NotApprovedRoute
    from app.pages.groups.groupspage import groups_page
    from app.pages.giftcardredeem.redeem import GiftcardRedeemRoute
    from app.pages.currencyexchange.controller import CurrencyExchangeRoute
    from app.routes.kofihandler import KofiHandlerRoute
    #from app.pages.invitekeys.handler import inviteKeyRoute
    from app.routes.discord_internal import DiscordInternal
    from app.routes.publicapi import PublicAPIRoute
    from app.pages.catalog.catalog import LibraryRoute
    from app.routes.discourse_sso import discourse_sso
    from app.pages.transactions.transactions import TransactionsRoute
    from app.routes.gametransactions import GameTransactionsRoute
    from app.pages.audiomigrator.audiomigrator import AudioMigratorRoute
    from app.routes.rbxapi import RBXAPIRoute
    from app.routes.legacydatapersistence import LegacyDataPersistenceRoute
    from app.routes.friendapi import FriendsAPIRoute
    from app.routes.inventoryapi import InventoryAPI
    from app.routes.usersapi import UsersAPI
    from app.routes.mobile import MobileAPIRoute
    from app.routes.gamesapi import GamesAPIRoute
    from app.routes.accountsettingsapi import AccountSettingsAPIRoute
    from app.routes.presenceapi import PresenceAPIRoute
    from app.routes.avatarapi import AvatarAPIRoute
    from app.routes.badgesapi import BadgesAPIRoute
    from app.pages.catalog.catalog import BadgesPageRoute
    from app.pages.users.users_page import users_page
    from app.routes.teleportservice import TeleportServiceRoute
    from app.routes.prometheus import PrometheusRoute
    from app.routes.rolimons import RolimonsAPI
    from app.routes.cryptomus_handler import CryptomusHandler
    app.register_blueprint(login, url_prefix="/")
    app.register_blueprint(signup, url_prefix="/")
    app.register_blueprint(static, url_prefix="/")
    app.register_blueprint(settings, url_prefix="/")
    app.register_blueprint(home, url_prefix="/")
    app.register_blueprint(AssetRoute, url_prefix="/")
    app.register_blueprint(AuthenticationRoute, url_prefix="/")
    app.register_blueprint(AdminRoute, url_prefix="/admin")
    app.register_blueprint(JobReportHandler, url_prefix="/")
    app.register_blueprint(ClientInfo, url_prefix="/")
    app.register_blueprint(Thumbnailer, url_prefix="/internal")
    app.register_blueprint(ImageRoute, url_prefix="/")
    app.register_blueprint(FFlagRoute, url_prefix="/")
    app.register_blueprint(Profile, url_prefix="/")
    app.register_blueprint(GameJoinRoute, url_prefix="/")
    app.register_blueprint(MarketPlaceRoute, url_prefix="/marketplace")
    app.register_blueprint(EconomyV1Route, url_prefix="/")
    app.register_blueprint(PresenceRoute, url_prefix="/presence")
    app.register_blueprint(MessageRoute, url_prefix="/messages")
    #app.register_blueprint(ClothingMigratorRoute, url_prefix="/")
    app.register_blueprint(CatalogRoute, url_prefix="/catalog")
    app.register_blueprint(AvatarRoute, url_prefix="/")
    app.register_blueprint(PointsServiceRoute, url_prefix="/")
    app.register_blueprint(DataStoreRoute, url_prefix="/")
    app.register_blueprint(ClientPages, url_prefix="/")
    app.register_blueprint(LuaWebServiceRoute, url_prefix="/")
    app.register_blueprint(DevelopPagesRoute, url_prefix="/")
    app.register_blueprint(BootstrapperRoute, url_prefix="/")
    app.register_blueprint(StudioPagesRoute, url_prefix="/")
    app.register_blueprint(GamePagesRoute, url_prefix="/")
    app.register_blueprint(MembershipPages, url_prefix="/")
    app.register_blueprint(AssetRateRoute, url_prefix="/")
    app.register_blueprint(TradesPageRoute, url_prefix="/")
    app.register_blueprint(SetsRoute, url_prefix="/")
    app.register_blueprint(NotApprovedRoute, url_prefix="/")
    app.register_blueprint(groups_page, url_prefix="/")
    app.register_blueprint(GiftcardRedeemRoute, url_prefix="/")
    app.register_blueprint(CurrencyExchangeRoute, url_prefix="/currency-exchange")
    app.register_blueprint(KofiHandlerRoute, url_prefix="/")
    #app.register_blueprint(inviteKeyRoute, url_prefix="/")
    app.register_blueprint(DiscordInternal, url_prefix="/internal/discord_bot")
    app.register_blueprint(PublicAPIRoute, url_prefix="/public-api")
    app.register_blueprint(LibraryRoute, url_prefix="/library")
    app.register_blueprint(discourse_sso, url_prefix="/discourse")
    app.register_blueprint(TransactionsRoute, url_prefix="/transactions")
    app.register_blueprint(GameTransactionsRoute, url_prefix="/")
    app.register_blueprint(AudioMigratorRoute, url_prefix="/")
    app.register_blueprint(RBXAPIRoute, url_prefix="/")
    app.register_blueprint(LegacyDataPersistenceRoute, url_prefix="/persistence/legacy")
    app.register_blueprint(FriendsAPIRoute, url_prefix="/")
    app.register_blueprint(InventoryAPI, url_prefix="/")
    app.register_blueprint(UsersAPI, url_prefix="/")
    app.register_blueprint(MobileAPIRoute, url_prefix="/")
    app.register_blueprint(GamesAPIRoute, url_prefix="/")
    app.register_blueprint(AccountSettingsAPIRoute, url_prefix="/")
    app.register_blueprint(PresenceAPIRoute, url_prefix="/")
    app.register_blueprint(AvatarAPIRoute, url_prefix="/")
    app.register_blueprint(BadgesAPIRoute, url_prefix="/")
    app.register_blueprint(BadgesPageRoute, url_prefix="/badges")
    app.register_blueprint(users_page, url_prefix="/")
    app.register_blueprint(TeleportServiceRoute, url_prefix="/reservedservers")
    app.register_blueprint(PrometheusRoute, url_prefix="/")
    app.register_blueprint(RolimonsAPI, url_prefix="/api/internal_rolimons")
    app.register_blueprint(CryptomusHandler, url_prefix="/cryptomus_service")

    def ConvertDatetimeToDayMonthYear(date):
        return date.strftime("%d/%m/%Y")

    app.jinja_env.globals.update(round=round, b64decode=base64.b64decode, len=len, ConvertDatetimeToDayMonthYear=ConvertDatetimeToDayMonthYear, datetime_utcnow = datetime.utcnow)

    @app.before_request
    def before_request():
        BrowserUserAgent = request.headers.get('User-Agent', default="Unknown")
        if "Roblox" not in BrowserUserAgent:
            if request.method == "GET":
                CloudFlareScheme = request.headers.get('CF-Visitor')
                if CloudFlareScheme is not None:
                    if "https" not in CloudFlareScheme:
                        return redirect(request.url.replace("http://", "https://", 1), code=301)
        elif BrowserUserAgent == "Roblox/WinInet":
            requestReferer = request.headers.get( key = "Referer", default = None )
            if requestReferer is not None:
                try:
                    if urlparse( requestReferer ).hostname[ -len( config_class.BaseDomain ): ] != config_class.BaseDomain:
                        logging.warn(f"Bad Referer - ref : {requestReferer} - target : {request.url}")
                        return "Bad Referer", 403
                except:
                    pass 
    
    @app.after_request
    def after_request( response : Response ):
        logging.info(f"{response.status_code} - {request.host} - {request.path} - {request.args}")
        if hasattr(response, 'direct_passthrough') and not response.direct_passthrough:
            UserObj : User = auth.GetCurrentUser()
            if UserObj is not None:
                if UserObj.accountstatus != 1:
                    auth.invalidateToken(request.cookies.get(".ROBLOSECURITY"))
                    session["not-approved-viewer"] = UserObj.id
                    resp = make_response(redirect("/not-approved"))
                    resp.set_cookie(".ROBLOSECURITY", "", expires=0)
                    return resp
            if request.cookies.get(key="t", default=None, type=str) is None:
                NewToken = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(128))
                response.set_cookie("t", NewToken, expires=datetime.utcnow() + timedelta(days=365), domain=f".{config_class.BaseDomain}")
        if "not-approved-viewer" in session:
            UserObj : User = auth.GetCurrentUser()
            if UserObj is not None:
                session.pop("not-approved-viewer")
        return response

    @app.context_processor
    def inject_user():
        if ".ROBLOSECURITY" in request.cookies:
            AuthenticatedUser : User = auth.GetCurrentUser()
            if AuthenticatedUser is None:
                return {}
            
            def award_daily_login_bonus():
                if redis_controller.get(f"daily_login_bonus:{str(AuthenticatedUser.id)}") is not None:
                    return
                if AuthenticatedUser.created > datetime.utcnow() - timedelta( days = 1 ):
                    return
                if GameSessionLog.query.filter_by(user_id=AuthenticatedUser.id).filter( GameSessionLog.joined_at > datetime.utcnow() - timedelta( days = 3 ) ).first() is None:
                    return
                
                redis_controller.setex(f"daily_login_bonus:{str(AuthenticatedUser.id)}", 60 * 60 * 24 ,"1")
                IncrementTargetBalance(AuthenticatedUser, 10, 1)
                transactions.CreateTransaction(
                    Reciever = AuthenticatedUser,
                    Sender = User.query.filter_by(id=1).first(),
                    CurrencyAmount = 10,
                    CurrencyType = 1,
                    TransactionType = TransactionType.BuildersClubStipend,
                    CustomText = "Daily Login Bonus"
                )

            if redis_controller.exists(f"award_daily_login_bonus_attempt:{str(AuthenticatedUser.id)}") is None:
                redis_controller.setex(f"award_daily_login_bonus_attempt:{str(AuthenticatedUser.id)}", 60, "1")
                award_daily_login_bonus()
            
            unreadMessages = Message.query.filter_by(recipient_id=AuthenticatedUser.id, read=False).count()
            inboundTrades = UserTrade.query.filter_by(recipient_userid=AuthenticatedUser.id, status=TradeStatus.Pending).count()
            friendRequests = FriendRequest.query.filter_by(requestee_id=AuthenticatedUser.id).count()
            AuthenticatedUser.lastonline = datetime.utcnow()
            db.session.commit()
            userRobux, userTix = GetUserBalance(AuthenticatedUser)
            isAdministrator = IsUserAnAdministrator( AuthenticatedUser )
            PendingAssetsCount = 0
            if isAdministrator:
                PendingAssetsCount = GetAmountOfPendingAssets()
            
            return {
                "currentuser": {
                    "id": AuthenticatedUser.id,
                    "username": AuthenticatedUser.username,
                    "robux": userRobux,
                    "tix": userTix,
                    "unread_messages": unreadMessages,
                    "inbound_trades": inboundTrades,
                    "friend_requests": friendRequests,
                    "is_admin": isAdministrator,
                    "pending_asset_count": PendingAssetsCount
                },
            }
        return {}
    from app.build_version import BUILD_HASH
    @app.context_processor
    def inject_version():
     return {
        "BuildVersionDontGetThisMixedUpCuh": BUILD_HASH
    }
    @app.context_processor
    def inject_website_wide_message():
        if redis_controller.exists("website_wide_message"):
            url_pattern = re.compile(r'(https?://\S+)')
            website_message = website_wide_message=redis_controller.get("website_wide_message")
            website_message = url_pattern.sub(r'<a href="\1">\1</a>', website_message)
            return dict(website_wide_message=website_message)
        return {}

    @app.context_processor
    def injecthcaptcha_sitekey():
        return dict(turnstilekey=Config.CloudflareTurnstileSiteKey)

    @app.route('/')
    def main():
        if "user" in session:
            return redirect("/home")
        else:
            return redirect("/login")

    @app.errorhandler(404)
    def page_not_found(e):
        BrowserUserAgent = request.headers.get('User-Agent')
        if BrowserUserAgent is not None:
            if "RobloxStudio" in BrowserUserAgent:
                return "<h1 style='margin:0;'>404 - Page not found</h1><br><a style='margin:0;' href='/ide/welcome'>Return to homepage</a>"
        #logging.error(f"404 - {request.path}")
        return render_template("404.html"), 404

    @app.errorhandler(403)
    def page_forbidden(e):
        BrowserUserAgent = request.headers.get('User-Agent')
        if BrowserUserAgent is not None:
            if "RobloxStudio" in BrowserUserAgent:
                return "<h1 style='margin:0;'>403 - Forbidden</h1><br><a style='margin:0;' href='/ide/welcome'>Return to homepage</a>"
        return render_template("403.html"), 403
    
    @app.errorhandler(405)
    def page_forbidden(e):
        BrowserUserAgent = request.headers.get('User-Agent')
        if BrowserUserAgent is not None:
            if "RobloxStudio" in BrowserUserAgent:
                return "<h1 style='margin:0;'>405 - Method Not Allowed</h1><br><a style='margin:0;' href='/ide/welcome'>Return to homepage</a>"
        return render_template("405.html"), 405
    
    @app.errorhandler(500)
    def page_internal_server_error(e):
        exc_type, exc_value, exc_traceback = sys.exc_info()
        PageRoute = request.path
        return render_template("500.html", error={
            "type": exc_type,
            "value": exc_value,
            "traceback": str(traceback.format_exc())
        }, page=PageRoute), 500
    

    @app.errorhandler(429)
    def ratelimit_handler(e):
        return jsonify({"error": "You are being rate limited.", "message": "You are being rate limited.", "success": False}), 429
    
    if config_class.ASSETMIGRATOR_USE_PROXIES:
        redis_controller.delete("assetmigrator_proxies")
        with open(config_class.ASSETMIGRATOR_PROXY_LIST_LOCATION, "r") as f:
            LoadedProxies = 0
            for line in f:
                if line.strip() != "":
                    LoadedProxies += 1
                    redis_controller.sadd("assetmigrator_proxies", line.strip())
        logging.info(f"Loaded {LoadedProxies} proxies")

    try:
        if not redis_controller.exists("coregui_ids_cooldown"):
            with app.app_context():
                redis_controller.setex("coregui_ids_cooldown", 60 * 60, "1")
                AllCoreGui = os.listdir("./app/files/CoreGui")
                redis_controller.delete("coregui_ids")
                for CoreGui in AllCoreGui:
                    try:
                        redis_controller.sadd("coregui_ids", int(CoreGui))
                    except:
                        logging.error(f"Failed to load CoreGui file {CoreGui}")

                    AssetObj : Asset = Asset.query.filter_by(id=int(CoreGui)).first()
                    if AssetObj is None:
                        AssetObj = Asset(
                            name = "CoreGui",
                            created_at = datetime.utcnow(),
                            updated_at = datetime.utcnow(),
                            asset_type = AssetType.Lua,
                            creator_id = 1,
                            creator_type = 0,
                            moderation_status = 0
                        )
                        AssetObj.id = int(CoreGui)
                        db.session.add(AssetObj)
                        db.session.commit()
                        logging.info(f"Created CoreGui asset {CoreGui}")
                    CoreGuiContent = open(f"./app/files/CoreGui/{CoreGui}", "r").read()
                    if int(CoreGui) in TwelveClientAssets:
                        CoreGuiContent = signscript.signUTF8(f"%{CoreGui}%\r\n{CoreGuiContent}", addNewLine=False, twelveclient=True)
                    else:
                        CoreGuiContent = signscript.signUTF8(f"--rbxassetid%{CoreGui}%\r\n{CoreGuiContent}", addNewLine=False)

                    CoreGuiHash = hashlib.sha512(CoreGuiContent.encode("utf-8")).hexdigest()
                    AssetVersionObj : AssetVersion = assetversion.GetLatestAssetVersion( AssetObj )
                    if AssetVersionObj is None or AssetVersionObj.content_hash != CoreGuiHash:
                        s3helper.UploadBytesToS3(
                            CoreGuiContent.encode("utf-8"),
                            CoreGuiHash
                        )
                        assetversion.CreateNewAssetVersion(
                            AssetObj,
                            CoreGuiHash,
                            CoreGuiContent,
                        )
                logging.info(f"Loaded {len(AllCoreGui)} CoreGui files")
    except Exception as e:
        logging.error(f"Failed to load CoreGui files: {e}")

    logging.info("App created")
    return app
