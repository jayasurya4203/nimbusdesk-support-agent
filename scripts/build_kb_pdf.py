"""Generate the knowledge-base PDF (`data/password_reset_guide.pdf`).

The PDF is committed to the repository; this script exists so the document can
be regenerated reproducibly. Requires the optional dev dependency `reportlab`.

Usage: python scripts/build_kb_pdf.py
"""

from __future__ import annotations

from pathlib import Path

from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    ListFlowable,
    ListItem,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
)

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data" / "password_reset_guide.pdf"

TITLE = "NimbusDesk Password and Account Recovery Guide"
SUBTITLE = "Support knowledge base | Document ID KB-1007 | Last updated 2026-09-24"

FOOTER = "NimbusDesk Support | KB-1007 | Internal and customer-shareable"


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "KbTitle",
            parent=base["Title"],
            fontName="Helvetica-Bold",
            fontSize=22,
            leading=26,
            spaceAfter=10,
        ),
        "subtitle": ParagraphStyle(
            "KbSubtitle",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=9.5,
            textColor="#555555",
            spaceAfter=22,
        ),
        "h1": ParagraphStyle(
            "KbH1",
            parent=base["Heading1"],
            fontName="Helvetica-Bold",
            fontSize=14,
            leading=18,
            spaceBefore=14,
            spaceAfter=8,
            textColor="#12355b",
        ),
        "h2": ParagraphStyle(
            "KbH2",
            parent=base["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=11.5,
            leading=15,
            spaceBefore=10,
            spaceAfter=5,
        ),
        "body": ParagraphStyle(
            "KbBody",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=10,
            leading=14.5,
            spaceAfter=7,
        ),
        "note": ParagraphStyle(
            "KbNote",
            parent=base["BodyText"],
            fontName="Helvetica-Oblique",
            fontSize=9.5,
            leading=13.5,
            textColor="#444444",
            backColor="#f2f6fa",
            borderPadding=8,
            spaceBefore=6,
            spaceAfter=10,
        ),
    }


def _bullets(items: list[str], style: ParagraphStyle) -> ListFlowable:
    return ListFlowable(
        [ListItem(Paragraph(item, style), leftIndent=14) for item in items],
        bulletType="bullet",
        start="circle",
        leftIndent=16,
        spaceAfter=8,
    )


def _footer(canvas, doc) -> None:  # noqa: ANN001 - reportlab callback signature
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor("#777777")
    canvas.drawString(0.9 * inch, 0.55 * inch, FOOTER)
    canvas.drawRightString(LETTER[0] - 0.9 * inch, 0.55 * inch, f"Page {doc.page}")
    canvas.restoreState()


def build() -> Path:
    s = _styles()
    doc = SimpleDocTemplate(
        str(OUTPUT),
        pagesize=LETTER,
        leftMargin=0.9 * inch,
        rightMargin=0.9 * inch,
        topMargin=0.8 * inch,
        bottomMargin=0.8 * inch,
        title=TITLE,
        author="NimbusDesk Support",
        subject="Password reset, MFA reset, and account lockout recovery",
    )

    story = [
        Paragraph(TITLE, s["title"]),
        Paragraph(SUBTITLE, s["subtitle"]),
        Paragraph(
            "This guide covers self-serve password recovery, MFA reset, account lockout, and "
            "admin-initiated recovery for NimbusDesk. It applies to all plans and to both the "
            "web application and the mobile apps. Steps that require workspace administration "
            "are marked as such.",
            s["body"],
        ),
        Paragraph("1. Self-serve password reset", s["h1"]),
        Paragraph(
            "Use this path when the user can still receive email at the address on their "
            "NimbusDesk profile.",
            s["body"],
        ),
        _bullets(
            [
                "Open <b>https://app.nimbusdesk.io/forgot-password</b>.",
                "Enter the email address exactly as it appears on the member profile.",
                "Open the email from <b>security@nimbusdesk.io</b> and select <b>Reset password</b>.",
                "Choose a new password: at least 12 characters, not reused from the last 5 passwords, "
                "and not a known breached password.",
                "Sign in again. All other sessions remain signed in unless the user selects "
                "<b>Sign out of all devices</b> during reset.",
            ],
            s["body"],
        ),
        Paragraph(
            "Reset links are single-use and expire after 30 minutes. A link that has already been "
            "opened cannot be reused. Request a new link if it has expired.",
            s["note"],
        ),
        Paragraph("If the reset email does not arrive", s["h2"]),
        _bullets(
            [
                "Check spam, quarantine, and the organization's email security gateway.",
                "Confirm the address on the profile; an alias or distribution list will not receive the message.",
                "Wait 60 minutes. Only 3 reset emails are sent per address per hour; further requests are dropped.",
                "Ask IT to allowlist <b>nimbusdesk.io</b> and the sending IP ranges published at "
                "https://trust.nimbusdesk.io/sending-ips.",
                "If a link-scanning gateway opens links automatically, the token can be consumed before the user "
                "clicks it. The user then sees 'This link is no longer valid'. Request a new link and, if this repeats, "
                "ask IT to exclude NimbusDesk reset links from pre-fetching.",
            ],
            s["body"],
        ),
        PageBreak(),
        Paragraph("2. Account lockout", s["h1"]),
        Paragraph(
            "NimbusDesk locks password sign-in after 5 consecutive failed attempts. The first lock "
            "lasts 15 minutes. Each lock within a rolling 24-hour window doubles the duration, up to "
            "a maximum of 60 minutes. A successful sign-in resets the counter.",
            s["body"],
        ),
        _bullets(
            [
                "Wait for the lock to expire, then sign in again.",
                "Use the password reset flow if the password is unknown. A successful reset clears the lock.",
                "Workspace Admins can unlock a member from <b>Settings → Members → member → Unlock sign-in</b>.",
                "SSO-enforced members cannot be unlocked in NimbusDesk; the identity provider controls their lockout. "
                "Unlock the account in the IdP or ask the IdP administrator to reset the credential.",
                "If a user is locked out because of repeated MFA failures, see section 3.",
            ],
            s["body"],
        ),
        Paragraph(
            "Support cannot unlock accounts directly and cannot verify a password. Admins and Owners "
            "unlock members themselves; Identity &amp; Access handles cases where no admin is available.",
            s["note"],
        ),
        Paragraph("3. MFA reset", s["h1"]),
        Paragraph("A member may lose access to their authenticator app or security key.", s["body"]),
        _bullets(
            [
                "If the member has a saved recovery code, use it at the MFA prompt and enroll a new device.",
                "If no recovery code is available, the workspace Owner or an Admin can reset MFA from "
                "<b>Settings → Members → member → Reset MFA</b>. The member must sign in again and re-enroll.",
                "An Admin cannot reset their own MFA; another Owner or Admin must do it.",
                "For SSO-enforced members, MFA is managed by the identity provider. Reset the factor in the IdP.",
                "Every MFA reset is recorded in the audit log and triggers an email to the member.",
            ],
            s["body"],
        ),
        Paragraph(
            "Security note: NimbusDesk support never asks for a password, an MFA code, or a recovery "
            "code. Do not share screenshots containing codes.",
            s["note"],
        ),
        PageBreak(),
        Paragraph("4. Admin-initiated recovery", s["h1"]),
        Paragraph(
            "Use this path when the member cannot access their email or cannot complete self-serve "
            "recovery.",
            s["body"],
        ),
        _bullets(
            [
                "The workspace Owner or an Admin signs in and opens <b>Settings → Members</b>.",
                "Select the member, then choose <b>Send password reset</b> or <b>Reset MFA</b>.",
                "If the member's email is wrong, update the member email first. This requires Owner or Admin rights.",
                "Ask the member to sign in immediately after the reset; temporary passwords are not used.",
                "If the member is the only Owner, transfer ownership or use the break-glass Owner before making changes.",
            ],
            s["body"],
        ),
        Paragraph("5. SSO-enforced accounts", s["h1"]),
        Paragraph(
            "When a workspace enforces SSO, NimbusDesk does not issue password reset emails. The "
            "member signs in through the identity provider and resets the password or MFA factor "
            "there. The one exception is the break-glass Owner, who retains a password for emergency "
            "access.",
            s["body"],
        ),
        _bullets(
            [
                "Confirm that SSO is enforced in Settings → Security → SSO.",
                "If the IdP account is locked, the IdP administrator must unlock it.",
                "If the IdP is unavailable, the break-glass Owner can sign in with a password and temporarily disable enforcement.",
                "Never disable SSO enforcement on a customer's behalf from support.",
            ],
            s["body"],
        ),
        Paragraph("6. Security practices", s["h1"]),
        _bullets(
            [
                "Never share a password or MFA code with anyone, including support.",
                "Use a unique password and a password manager.",
                "Review active sessions in <b>Settings → Security → Sessions</b> and sign out unrecognized devices.",
                "If an account compromise is suspected, revoke API keys, sign out all sessions, and escalate to Security Operations.",
            ],
            s["body"],
        ),
        Paragraph("7. When to escalate", s["h1"]),
        Paragraph(
            "Escalate to Identity &amp; Access when: no workspace Admin or Owner is available to reset "
            "MFA or update an email; the only Owner has lost access; an ownership transfer is required; "
            "or the account may be compromised. Include the workspace ID, member email, steps already "
            "attempted, exact error messages, and timestamps in UTC. Never include passwords, MFA codes, "
            "or recovery codes in the handoff.",
            s["body"],
        ),
    ]

    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return OUTPUT


if __name__ == "__main__":
    path = build()
    print(f"Wrote {path} ({path.stat().st_size / 1024:.1f} KB)")
