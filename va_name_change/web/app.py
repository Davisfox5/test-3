"""Flask routes for the Virginia Name Change web UI."""

from __future__ import annotations

import os
import re
from datetime import date, datetime

from flask import (
    Blueprint,
    abort,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)

from va_name_change.agents.filing import (
    format_instructions,
    get_filing_instructions,
    prepare_filing,
)
from va_name_change.agents.forms import generate_all_forms
from va_name_change.agents.post_decree import (
    build_update_plan,
    format_plan,
    mark_update_complete,
)
from va_name_change.agents.status_tracker import (
    InvalidTransitionError,
    build_default_timeline,
    safe_advance,
)
from va_name_change.config import config
from va_name_change.models import (
    Address,
    DownstreamUpdate,
    NameChangePetition,
    PetitionStatus,
)
from va_name_change.utils.crypto import encrypt
from va_name_change.utils.jurisdiction import (
    JurisdictionError,
    list_supported_jurisdictions,
    resolve_jurisdiction,
)
from va_name_change.web import store

bp = Blueprint("main", __name__)

# ---------------------------------------------------------------------------
# Validation helpers (mirrors intake agent logic)
# ---------------------------------------------------------------------------

_SSN_RE = re.compile(r"^\d{3}-?\d{2}-?\d{4}$")
_ZIP_RE = re.compile(r"^\d{5}(-\d{4})?$")


def _parse_date(raw: str) -> date | None:
    for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw.strip(), fmt).date()
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@bp.route("/")
def index():
    petitions = store.list_all()
    return render_template("index.html", petitions=petitions)


# -- Intake wizard ----------------------------------------------------------

@bp.route("/intake/step1", methods=["GET", "POST"])
def intake_step1():
    if request.method == "POST":
        current_name = request.form.get("current_name", "").strip()
        desired_name = request.form.get("desired_name", "").strip()
        reason = request.form.get("reason", "").strip()

        errors = []
        if not current_name:
            errors.append("Current legal name is required.")
        if not desired_name:
            errors.append("Desired new name is required.")
        if not reason:
            errors.append("Reason for name change is required.")

        if errors:
            for e in errors:
                flash(e, "error")
            return render_template("intake/step1_identity.html",
                                   current_name=current_name,
                                   desired_name=desired_name, reason=reason)

        session["intake"] = {
            "current_name": current_name,
            "desired_name": desired_name,
            "reason": reason,
        }
        return redirect(url_for("main.intake_step2"))

    data = session.get("intake", {})
    return render_template("intake/step1_identity.html",
                           current_name=data.get("current_name", ""),
                           desired_name=data.get("desired_name", ""),
                           reason=data.get("reason", ""))


@bp.route("/intake/step2", methods=["GET", "POST"])
def intake_step2():
    if "intake" not in session:
        return redirect(url_for("main.intake_step1"))

    if request.method == "POST":
        dob_raw = request.form.get("dob", "").strip()
        pob_raw = request.form.get("place_of_birth", "").strip()
        ssn_raw = request.form.get("ssn", "").strip()

        errors = []
        dob = _parse_date(dob_raw)
        if not dob:
            errors.append("Date of birth must be MM/DD/YYYY or YYYY-MM-DD.")
        if not pob_raw:
            errors.append("Place of birth is required.")
        if not _SSN_RE.match(ssn_raw):
            errors.append("SSN must be in the format 123-45-6789 or 123456789.")

        if errors:
            for e in errors:
                flash(e, "error")
            return render_template("intake/step2_personal.html",
                                   dob=dob_raw, place_of_birth=pob_raw, ssn=ssn_raw)

        session["intake"]["dob"] = dob.isoformat()
        session["intake"]["place_of_birth"] = pob_raw
        session["intake"]["ssn_last4"] = ssn_raw.replace("-", "")[-4:]
        session["intake"]["ssn_encrypted"] = encrypt(ssn_raw.replace("-", ""))
        session.modified = True
        return redirect(url_for("main.intake_step3"))

    data = session.get("intake", {})
    return render_template("intake/step2_personal.html",
                           dob=data.get("dob", ""),
                           place_of_birth=data.get("place_of_birth", ""),
                           ssn="")


@bp.route("/intake/step3", methods=["GET", "POST"])
def intake_step3():
    if "intake" not in session:
        return redirect(url_for("main.intake_step1"))

    jurisdictions = list_supported_jurisdictions()

    if request.method == "POST":
        street = request.form.get("street", "").strip()
        city = request.form.get("city", "").strip()
        county = request.form.get("county", "").strip()
        zip_code = request.form.get("zip_code", "").strip()

        errors = []
        if not street:
            errors.append("Street address is required.")
        if not city:
            errors.append("City is required.")
        if not county:
            errors.append("County / independent city is required.")
        if not _ZIP_RE.match(zip_code):
            errors.append("ZIP code must be 5 digits (optionally +4).")

        if errors:
            for e in errors:
                flash(e, "error")
            return render_template("intake/step3_address.html",
                                   street=street, city=city, county=county,
                                   zip_code=zip_code, jurisdictions=jurisdictions)

        session["intake"]["street"] = street
        session["intake"]["city"] = city
        session["intake"]["county"] = county
        session["intake"]["zip_code"] = zip_code
        session.modified = True
        return redirect(url_for("main.intake_step4"))

    data = session.get("intake", {})
    return render_template("intake/step3_address.html",
                           street=data.get("street", ""),
                           city=data.get("city", ""),
                           county=data.get("county", ""),
                           zip_code=data.get("zip_code", ""),
                           jurisdictions=jurisdictions)


@bp.route("/intake/step4", methods=["GET", "POST"])
def intake_step4():
    data = session.get("intake")
    if not data or "county" not in data:
        return redirect(url_for("main.intake_step1"))

    addr = Address(
        street=data["street"],
        city=data["city"],
        county=data["county"],
        zip_code=data["zip_code"],
    )

    try:
        court = resolve_jurisdiction(addr)
    except JurisdictionError as exc:
        flash(str(exc), "error")
        return redirect(url_for("main.intake_step3"))

    if request.method == "POST":
        # Build the petition
        petition = NameChangePetition(
            current_legal_name=data["current_name"],
            desired_name=data["desired_name"],
            reason=data["reason"],
            dob=date.fromisoformat(data["dob"]),
            place_of_birth=data.get("place_of_birth", ""),
            ssn_encrypted=data["ssn_encrypted"],
            address=addr,
            jurisdiction=court,
            downstream_updates=[
                DownstreamUpdate(agency="SSA", notes="Must be updated first"),
                DownstreamUpdate(agency="VA DMV", depends_on=["SSA"]),
                DownstreamUpdate(agency="US Passport", depends_on=["SSA"]),
                DownstreamUpdate(agency="Birth Certificate", depends_on=["SSA"]),
                DownstreamUpdate(agency="Voter Registration", depends_on=["VA DMV"]),
                DownstreamUpdate(agency="Banks / Financial", depends_on=["SSA"]),
                DownstreamUpdate(agency="Employer / HR", depends_on=["SSA"]),
                DownstreamUpdate(agency="Utilities"),
                DownstreamUpdate(agency="Professional Licenses", depends_on=["SSA"]),
            ],
        )
        petition.advance(PetitionStatus.INTAKE)

        # ── AUTO-GENERATE all forms and filing instructions ──
        generate_all_forms(petition)
        prepare_filing(petition)

        store.save(petition)

        # Clear intake from session, store petition ID
        session.pop("intake", None)
        session["petition_id"] = petition.petition_id

        flash("Your petition has been created and all documents generated automatically.", "success")
        return redirect(url_for("main.dashboard", petition_id=petition.petition_id))

    return render_template("intake/step4_confirm.html", data=data, court=court)


# -- Dashboard (unified automated view) ------------------------------------

@bp.route("/petition/<petition_id>/dashboard")
def dashboard(petition_id: str):
    petition = store.get(petition_id)
    if not petition:
        abort(404)

    # Ensure forms exist (idempotent — skips if already generated)
    if not petition.documents:
        generate_all_forms(petition)

    # Build filing instructions (read-only — does not mutate status)
    instructions = None
    if petition.jurisdiction and petition.status != PetitionStatus.INTAKE:
        instructions = get_filing_instructions(petition)

    # Build timeline
    timeline = build_default_timeline(petition)

    # Build post-decree plan if applicable
    plan = None
    if petition.status in (PetitionStatus.GRANTED, PetitionStatus.POST_DECREE_IN_PROGRESS, PetitionStatus.COMPLETED):
        if petition.status == PetitionStatus.GRANTED:
            safe_advance(petition, PetitionStatus.POST_DECREE_IN_PROGRESS)
        plan = build_update_plan(petition)

    return render_template("dashboard.html",
                           petition=petition,
                           instructions=instructions,
                           timeline=timeline,
                           plan=plan,
                           today=date.today())


# -- Milestone recording (automated status transitions) --------------------

@bp.route("/petition/<petition_id>/milestone", methods=["POST"])
def record_milestone(petition_id: str):
    petition = store.get(petition_id)
    if not petition:
        abort(404)

    action = request.form.get("action", "")

    try:
        if action == "filed":
            # forms_ready → filed (already happened via prepare_filing, but
            # the user is confirming they physically submitted)
            if petition.status == PetitionStatus.FORMS_READY:
                safe_advance(petition, PetitionStatus.FILED)
            flash("Filing confirmed. Waiting for hearing date.", "success")

        elif action == "hearing_scheduled":
            hearing_raw = request.form.get("hearing_date", "").strip()
            hearing_date = _parse_date(hearing_raw) if hearing_raw else None
            if hearing_date:
                petition.hearing_date = hearing_date
            safe_advance(petition, PetitionStatus.HEARING_SCHEDULED)
            flash("Hearing scheduled.", "success")

        elif action == "hearing_outcome":
            outcome = request.form.get("outcome", "").lower()
            if outcome == "granted":
                safe_advance(petition, PetitionStatus.GRANTED)
                flash("Congratulations! Your name change has been granted. "
                      "Your post-decree update plan is ready below.", "success")
            else:
                safe_advance(petition, PetitionStatus.DENIED)
                flash("Petition denied. Please consult an attorney for next steps.", "error")

    except InvalidTransitionError as exc:
        flash(str(exc), "error")

    return redirect(url_for("main.dashboard", petition_id=petition_id))


# -- Documents --------------------------------------------------------------

@bp.route("/petition/<petition_id>/documents")
def documents(petition_id: str):
    petition = store.get(petition_id)
    if not petition:
        abort(404)

    if not petition.documents:
        generate_all_forms(petition)

    return render_template("documents.html", petition=petition)


@bp.route("/petition/<petition_id>/documents/<filename>")
def download_document(petition_id: str, filename: str):
    petition = store.get(petition_id)
    if not petition:
        abort(404)

    out_dir = os.path.join(config.output_dir, petition_id)
    filepath = os.path.join(out_dir, filename)

    # Prevent path traversal
    if not os.path.realpath(filepath).startswith(os.path.realpath(out_dir)):
        abort(403)
    if not os.path.isfile(filepath):
        abort(404)

    return send_file(filepath, as_attachment=True)


# -- Filing -----------------------------------------------------------------

@bp.route("/petition/<petition_id>/filing")
def filing(petition_id: str):
    petition = store.get(petition_id)
    if not petition:
        abort(404)

    instructions = get_filing_instructions(petition) if petition.jurisdiction else None

    timeline = build_default_timeline(petition)
    return render_template("filing.html", petition=petition,
                           instructions=instructions, timeline=timeline,
                           today=date.today())


# -- Status -----------------------------------------------------------------

@bp.route("/petition/<petition_id>/status")
def status(petition_id: str):
    petition = store.get(petition_id)
    if not petition:
        abort(404)

    timeline = build_default_timeline(petition)
    all_statuses = [s for s in PetitionStatus]
    return render_template("status.html", petition=petition,
                           timeline=timeline, all_statuses=all_statuses)


@bp.route("/petition/<petition_id>/status/advance", methods=["POST"])
def advance_status(petition_id: str):
    petition = store.get(petition_id)
    if not petition:
        abort(404)

    target = request.form.get("target_status", "")
    try:
        target_status = PetitionStatus(target)
        safe_advance(petition, target_status)
        flash(f"Status advanced to {target_status.value}.", "success")
    except (ValueError, InvalidTransitionError) as exc:
        flash(str(exc), "error")

    return redirect(url_for("main.status", petition_id=petition_id))


# -- Post-decree ------------------------------------------------------------

@bp.route("/petition/<petition_id>/post-decree")
def post_decree(petition_id: str):
    petition = store.get(petition_id)
    if not petition:
        abort(404)

    plan = build_update_plan(petition)
    return render_template("post_decree.html", petition=petition, plan=plan)


@bp.route("/petition/<petition_id>/post-decree/complete", methods=["POST"])
def complete_update(petition_id: str):
    petition = store.get(petition_id)
    if not petition:
        abort(404)

    agency = request.form.get("agency", "")
    result = mark_update_complete(petition, agency)
    if result:
        flash(f"{agency} marked as complete.", "success")
    else:
        flash(f"Agency '{agency}' not found.", "error")

    # Redirect back to wherever the user came from (dashboard or post-decree page)
    referrer = request.referrer or ""
    if "dashboard" in referrer:
        return redirect(url_for("main.dashboard", petition_id=petition_id))
    return redirect(url_for("main.post_decree", petition_id=petition_id))
