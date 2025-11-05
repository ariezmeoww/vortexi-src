from flask import Blueprint, render_template, request, redirect, url_for, flash, session, abort
from app.models.user_ban import UserBan
from app.extensions import db, csrf, limiter, redis_controller
from app.models.user import User
from app.enums.BanType import BanType
from app.util import auth
from datetime import datetime, timedelta

NotApprovedRoute = Blueprint('notapproved', __name__, template_folder="pages")

BanTypeToText = {
    BanType.Warning: "Warning",
    BanType.Day1Ban: "Banned for 1 day",
    BanType.Day3Ban: "Banned for 3 days",
    BanType.Day7Ban: "Banned for 7 days",
    BanType.Day14Ban: "Banned for 14 days",
    BanType.Day30Ban: "Banned for 30 days",
    BanType.Deleted: "Account Deleted",
}

@NotApprovedRoute.route("/not-approved", methods=["GET"])
def not_approved():
    CurrentUser : User = auth.GetCurrentUser()
    if CurrentUser is not None:
        return redirect("/")

    if "not-approved-viewer" not in session:
        abort(404)
    
    UserObj : User = User.query.filter_by(id=session["not-approved-viewer"]).first()
    if UserObj is None:
        del session["not-approved-viewer"]
        abort(404)
    
    if UserObj.accountstatus == 4:
        del session["not-approved-viewer"]
        return redirect("/")
    
    if UserObj.accountstatus == 1:
        del session["not-approved-viewer"]
        return redirect("/")
    
    LatestUserBanObj : UserBan = UserBan.query.filter_by(userid=UserObj.id, acknowledged = False).order_by(UserBan.id.desc()).first()
    if LatestUserBanObj is None:
        del session["not-approved-viewer"]
        UserObj.accountstatus = 1
        db.session.commit()
        return redirect("/")
    hasBanExpired = False
    if LatestUserBanObj.expires_at is not None:
        if LatestUserBanObj.expires_at < datetime.utcnow():
            hasBanExpired = True
    
    return render_template("notapproved/banpage.html", user=UserObj, 
                           userban=LatestUserBanObj, 
                           banText=BanTypeToText[LatestUserBanObj.ban_type],
                           hasBanExpired=hasBanExpired)

@NotApprovedRoute.route("/not-approved", methods=["POST"])
def not_approved_post():
    CurrentUser : User = auth.GetCurrentUser()
    if CurrentUser is not None:
        return redirect("/")
    if "not-approved-viewer" not in session:
        abort(404)

    UserObj : User = User.query.filter_by(id=session["not-approved-viewer"]).first()
    if UserObj is None:
        del session["not-approved-viewer"]
        abort(404)
    
    if UserObj.accountstatus == 1:
        del session["not-approved-viewer"]
        return redirect("/")
    
    LatestUserBanObj : UserBan = UserBan.query.filter_by(userid=UserObj.id, acknowledged = False).order_by(UserBan.id.desc()).first()
    if LatestUserBanObj is None:
        del session["not-approved-viewer"]
        UserObj.accountstatus = 1
        db.session.commit()
        return redirect("/")
    if LatestUserBanObj.ban_type != BanType.Warning:
        flash("u can log back in now thank u", "error")
        return redirect("/not-approved")
    LatestUserBanObj.acknowledged = True
    UserObj.accountstatus = 1
    db.session.commit()
    del session["not-approved-viewer"]
    flash("Your account has been reactivated", "success")
    return redirect("/login")
