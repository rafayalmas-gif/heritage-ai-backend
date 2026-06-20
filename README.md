# Heritage WhatsApp AI Designer Backend

This project provides a simple Flask-based backend for Heritage Jewellers’ internal WhatsApp AI Designer. It handles incoming WhatsApp messages, verifies webhook subscriptions, downloads media, and relays commands and images to OpenAI. The AI then returns responses such as design suggestions, stone changes, caption generation, or product descriptions.

## Deploying on Render

1. **Create a Git repository** with this code (e.g. GitHub).
2. **Connect the repo** to Render when creating a new Web Service.
3. Render will detect the `render.yaml` file and configure build and start commands.
4. Add the following environment variables:
   - `VERIFY_TOKEN`: `heritage_verify_123`
   - `WHATSAPP_PHONE_ID`: `1189572340903084`
   - `WHATSAPP_TOKEN`: your Meta temporary or permanent access token
   - `OPENAI_API_KEY`: your OpenAI API key
   - `STAFF_NUMBERS`: comma-separated list of authorized staff numbers (E.164 format, e.g., `923001234567`)
   - `OPENAI_MODEL`: `gpt-4.1-mini` (or any supported model)

## Webhook Configuration (Meta)

In the Meta Developers portal under **WhatsApp** → **Configuration**:

- **Callback URL:** `https://YOUR_RENDER_SERVICE.onrender.com/webhook`
- **Verify Token:** `heritage_verify_123`
- Subscribe to **messages** events.

## Usage

- Staff send commands like `/stone change emerald to ruby`, `/model`, `/dress`, `/caption`, etc., to the WhatsApp number associated with this app.
- The backend forwards requests to OpenAI using the system prompt defined in `HERITAGE_SYSTEM_PROMPT` and returns an AI-generated response.
- All interactions are logged in `logs.jsonl` by default.
