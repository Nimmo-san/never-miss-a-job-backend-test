"""
Twilio webhook endpoints.

Twilio POSTs `application/x-www-form-urlencoded` bodies to these URLs and
expects a TwiML (XML) response back. Every field pulled out with `Form(...)`
below is one Twilio documents as part of that webhook's request:
https://www.twilio.com/docs/voice/twiml and
https://www.twilio.com/docs/messaging/twiml
"""

import logging

from fastapi import APIRouter, Form, Response
from twilio.twiml.messaging_response import MessagingResponse
from twilio.twiml.voice_response import Dial, VoiceResponse

from . import config, database

logger = logging.getLogger("never_miss_a_job.webhooks")

router = APIRouter(prefix="/webhooks")

# Twilio DialCallStatus values that mean the tradesperson did NOT pick up.
# ("completed" is the only "answered" outcome; everything else is a miss.)
MISSED_DIAL_STATUSES = {"busy", "no-answer", "failed", "canceled"}


def _twiml_response(twiml) -> Response:
    return Response(content=str(twiml), media_type="application/xml")


@router.post("/voice/incoming")
async def voice_incoming(
    CallSid: str = Form(...),
    From: str = Form(...),
    To: str = Form(...),
    CallStatus: str = Form(default=""),
):
    """Entry point: a customer is calling the dedicated number. Dial the
    tradesperson's real phone with a ring timeout; play the whisper only on
    their leg via the `url` on <Number>, before the two calls are bridged."""
    logger.info("Inbound call %s from %s to %s (status=%s)", CallSid, From, To, CallStatus)
    database.create_call(call_sid=CallSid, from_number=From, to_number=To, initial_status=CallStatus)

    response = VoiceResponse()

    if not config.TRADESPERSON_NUMBER:
        logger.error("TRADESPERSON_NUMBER is not configured -- cannot dial out for call %s", CallSid)
        response.say("Sorry, this line isn't fully set up yet. Please try again later.")
        return _twiml_response(response)

    dial = Dial(
        timeout=config.RING_TIMEOUT_SECONDS,
        action="/webhooks/voice/dial-status",
        method="POST",
        caller_id=config.TWILIO_NUMBER or None,
    )
    dial.number(config.TRADESPERSON_NUMBER, url="/webhooks/voice/whisper", method="POST")
    response.append(dial)

    return _twiml_response(response)


@router.post("/voice/whisper")
async def voice_whisper():
    """Fetched by Twilio only for the tradesperson's leg, at the moment they
    pick up -- so only they hear this, never the customer. Playback finishes
    and the call bridges to the customer automatically."""
    response = VoiceResponse()
    response.say(config.WHISPER_MESSAGE)
    return _twiml_response(response)


@router.post("/voice/dial-status")
async def voice_dial_status(
    CallSid: str = Form(...),
    From: str = Form(...),
    To: str = Form(...),
    DialCallStatus: str = Form(...),
):
    """Twilio calls this once the <Dial> attempt finishes, reporting how it
    ended. This is the "status callback" the architecture asks for."""
    logger.info("Dial for call %s finished with status=%s", CallSid, DialCallStatus)
    database.update_call_status(call_sid=CallSid, dial_call_status=DialCallStatus)

    response = VoiceResponse()

    if DialCallStatus not in MISSED_DIAL_STATUSES:
        # Tradesperson answered ("completed"). Nothing further for Week 1.
        return _twiml_response(response)

    database.get_or_create_open_conversation(
        customer_number=From,
        channel="call",
        source_event=f"missed_call:{DialCallStatus}",
        related_call_sid=CallSid,
    )

    # TODO (Week 2 hand-off point): this is where the real fallback + AI
    # agent take over. Once a call is confirmed missed, this is where we
    # should:
    #   1. Send an SMS to the customer (`From`) via the Twilio REST client
    #      (e.g. "Sorry we missed you -- what job do you need done?").
    #   2. Hand the resulting SMS thread to the AI qualification agent so it
    #      can ask qualifying questions and attempt to book the job.
    # Week 1 only logs the miss and opens a conversation record -- no
    # outbound message is sent and no AI logic runs yet.
    logger.info(
        "Missed call from %s (status=%s) -- conversation opened; SMS fallback "
        "and AI hand-off are Week 2 work",
        From,
        DialCallStatus,
    )

    response.say(config.MISSED_CALL_CALLER_MESSAGE)
    return _twiml_response(response)


@router.post("/messages/incoming")
async def messages_incoming(
    MessageSid: str = Form(...),
    From: str = Form(...),
    To: str = Form(...),
    Body: str = Form(default=""),
):
    """Handles both inbound SMS and inbound WhatsApp -- Twilio prefixes
    WhatsApp numbers with "whatsapp:", which is how we tell them apart. Point
    both the SMS webhook and the WhatsApp sandbox webhook at this same URL
    (see README)."""
    channel = "whatsapp" if From.startswith("whatsapp:") else "sms"
    logger.info("Inbound %s message %s from %s: %r", channel, MessageSid, From, Body)

    conversation_id = database.get_or_create_open_conversation(
        customer_number=From,
        channel=channel,
        source_event="inbound_message",
    )
    database.create_message(
        conversation_id=conversation_id,
        direction="inbound",
        channel=channel,
        from_number=From,
        to_number=To,
        body=Body,
        message_sid=MessageSid,
    )

    # TODO (Week 2 hand-off point): replace this placeholder acknowledgement
    # with a call into the AI qualification agent. It should read this
    # conversation's message history (database.list_messages), ask
    # qualifying questions (job type, urgency, location, availability), and
    # eventually offer/book a calendar slot instead of just acknowledging.
    reply_body = config.SMS_PLACEHOLDER_REPLY
    response = MessagingResponse()
    response.message(reply_body)

    database.create_message(
        conversation_id=conversation_id,
        direction="outbound",
        channel=channel,
        from_number=To,
        to_number=From,
        body=reply_body,
        message_sid=None,
    )

    return _twiml_response(response)
