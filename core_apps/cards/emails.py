from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.utils.translation import gettext_lazy as _
from loguru import logger


def send_virtual_card_topup_email(user, virtual_card, amount, new_balance) -> None:
    subject = _("Virtual Card Top-Up Confirmation")
    from_email = settings.DEFAULT_FROM_EMAIL
    recipient_list = [user.email]
    context = {
        "user_fullname": user.full_name,
        "card_last_four": virtual_card.card_number[-4:],
        "currency": virtual_card.bank_account.currency,
        "amount": amount,
        "new_balance": new_balance,
        "site_name": settings.SITE_NAME,
    }

    html_email = render_to_string("emails/virtual_card_topup.html", context)
    plain_email = strip_tags(html_email)
    email = EmailMultiAlternatives(subject, plain_email, from_email, recipient_list)
    email.attach_alternative(html_email, "text/html")

    try:
        email.send()
        logger.info(f"Virtual card top-up email sent successfully to: {user.email}")
    except Exception as e:
        logger.error(
            f"Failed to send virtual card top-up email to {user.email}: Error: {str(e)}"
        )
