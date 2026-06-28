# Heritage AI V7 Knowledge Integrated Backend

This version integrates the Heritage knowledge base into the backend prompts and command logic.

## Key upgrades

- Heritage Master Prompt added.
- Product DNA Lock added.
- Stronger `/model` rules for rings, bangles, necklaces and modest model styling.
- Stronger `/stone` rules and mixed-stone clarification.
- `/similar` rebuilt to avoid blank responses.
- `/similar` now sends text fallback even if WhatsApp image sending fails.
- Shopify `/products.json` catalog crawler added for better product images/prices.
- Debug logs added for `/similar`.

## Commands

Image commands:
- `/analyze`
- `/stone ruby`
- `/stone emerald`
- `/stone sapphire`
- `/polish white gold`
- `/polish yellow gold`
- `/polish ganga jamni`
- `/model`
- `/model closeup`
- `/model 3 options`
- `/similar`
- `/similar bangle`
- `/similar ring`
- `/similar earrings`
- `/similar necklace sets`
- `/more`
- `/refreshcatalog`

Content commands:
- `/caption`
- `/product`
- `/cad`
- `/bridal`
- `/collection`

## Deploy

1. Upload all files to GitHub.
2. Keep this folder structure:

app.py
config.py
requirements.txt
render.yaml
README.md
services/
prompts/

3. Render start command:
gunicorn app:app

4. After deployment, first send:
`/refreshcatalog`

5. Then test:
`/similar necklace sets`
`/model`
`/stone emerald`
`/analyze`
