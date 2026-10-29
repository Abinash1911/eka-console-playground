"""Channel and provider vocabularies, shared by the model, request schemas and schema registry.

Kept off the model to avoid an import cycle with ``integration.schemas``.
"""

CHANNEL_WHATSAPP = "whatsapp"
CHANNEL_TELEPHONY = "telephony"

CHANNEL_CHOICES = [
    (CHANNEL_WHATSAPP, "WhatsApp"),
    (CHANNEL_TELEPHONY, "Telephony"),
    # ("sms", "SMS"),      # future
    # ("email", "Email"),  # future
]

CHANNELS = tuple(value for value, _ in CHANNEL_CHOICES)

PROVIDER_CHOICES = [
    ("interakt", "Interakt"),
    ("interakt_tp", "EkaAgents"),
    ("turn_io", "Turn.io"),
    ("netcore", "Netcore"),
    ("meta", "Meta Cloud API"),
    ("twilio", "Twilio"),
    ("vobiz", "Vobiz"),
]

PROVIDERS = tuple(value for value, _ in PROVIDER_CHOICES)
