# Heritage AI V6 Production Backend

## Commands

/image commands:
- `/analyze`
- `/stone ruby`
- `/stone emerald`
- `/stone sapphire`
- `/stone yellow sapphire`
- `/polish white gold`
- `/polish yellow gold`
- `/polish ganga jamni`
- `/model`
- `/model 3 options`
- `/similar`
- `/similar bangle`
- `/similar ring`
- `/similar earrings`
- `/similar necklace set`
- `/more`
- `/refreshcatalog`

/content commands:
- `/caption`
- `/product`
- `/cad`
- `/bridal`
- `/collection`

## Deploy

1. Upload all files to GitHub.
2. Render start command:
   `gunicorn app:app`
3. Add environment variables from `.env.example`.
4. Test:
   `/refreshcatalog`
   `/analyze` with image
   `/similar bangle` with image
   `/stone ruby` with image
   `/model 3 options` with image

## Notes

- `/similar` uses website catalog crawling and Visual DNA scoring.
- Product image URLs are cached to Cloudinary before WhatsApp sending.
- `/stone` includes smart clarification for mixed stone zones.
- `/model` asks for product type confirmation if confidence is low.
