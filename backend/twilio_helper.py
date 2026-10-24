"""
twilio_helper.py — Sends SMS messages via Twilio
"""

import os
import logging
from typing import List

log = logging.getLogger(__name__)

# Try to import twilio, but don't fail if not installed
try:
    from twilio.rest import Client
    TWILIO_AVAILABLE = True
except ImportError:
    TWILIO_AVAILABLE = False
    log.warning("Twilio not installed. Install with: pip install twilio")


def send_sms(message_body: str, to_phone: str = None) -> dict:
    """
    Send an SMS via Twilio.
    
    Returns: {'success': bool, 'message_sid': str, 'error': str}
    """
    account_sid = os.environ.get("TWILIO_ACCOUNT_SID")
    auth_token = os.environ.get("TWILIO_AUTH_TOKEN")
    from_phone = os.environ.get("TWILIO_FROM_PHONE")
    to_phone = to_phone or os.environ.get("TWILIO_TO_PHONE")
    
    result = {'success': False, 'message_sid': None, 'error': None}
    
    if not TWILIO_AVAILABLE:
        result['error'] = "Twilio library not installed"
        log.error(result['error'])
        return result
    
    if not all([account_sid, auth_token, from_phone, to_phone]):
        result['error'] = "Missing Twilio credentials (TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_PHONE, TWILIO_TO_PHONE)"
        log.error(result['error'])
        return result
    
    try:
        client = Client(account_sid, auth_token)
        message = client.messages.create(
            body=message_body,
            from_=from_phone,
            to=to_phone
        )
        result['success'] = True
        result['message_sid'] = message.sid
        log.info("SMS sent successfully (SID: %s)", message.sid)
        return result
    except Exception as e:
        result['error'] = str(e)
        log.error("Twilio SMS error: %s", e)
        return result


def format_sms_line(label: str, value: str, max_width: int = 40) -> str:
    """Format a label-value pair for SMS display."""
    if len(label) + len(value) > max_width:
        return f"{label}:\n{value}"
    return f"{label}: {value}"
