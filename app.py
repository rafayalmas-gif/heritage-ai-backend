import os,json,base64,re,time,threading,requests
from io import BytesIO
from datetime import datetime,timezone
from flask import Flask,request,jsonify
from openai import OpenAI
from PIL import Image
from bs4 import BeautifulSoup
import cloudinary, cloudinary.uploader

app=Flask(__name__)
VERIFY_TOKEN=os.getenv("VERIFY_TOKEN","heritage_verify_123")
WHATSAPP_TOKEN=os.getenv("WHATSAPP_TOKEN","")
WHATSAPP_PHONE_ID=os.getenv("WHATSAPP_PHONE_ID","")
OPENAI_API_KEY=os.getenv("OPENAI_API_KEY","")
OPENAI_MODEL=os.getenv("OPENAI_MODEL","gpt-4.1-mini")
OPENAI_IMAGE_MODEL=os.getenv("OPENAI_IMAGE_MODEL","gpt-image-1")
STAFF_NUMBERS=[x.strip() for x in os.getenv("STAFF_NUMBERS","").split(",") if x.strip()]
MANAGER_NUMBERS=[x.strip() for x in os.getenv("MANAGER_NUMBERS","").split(",") if x.strip()]
LOG_FILE=os.getenv("LOG_FILE","logs.jsonl")
CATALOG_FILE=os.getenv("CATALOG_FILE","heritage_catalog.json")
HERITAGE_SITE=os.getenv("HERITAGE_SITE","https://heritagejewels.com.pk").rstrip("/")
CATALOG_REFRESH_HOURS=int(os.getenv("CATALOG_REFRESH_HOURS","12"))
CATALOG_MAX_PRODUCTS=int(os.getenv("CATALOG_MAX_PRODUCTS","250"))
CATALOG_ANALYZE_IMAGES=os.getenv("CATALOG_ANALYZE_IMAGES","true").lower()=="true"
CATALOG_COLLECTIONS=[x.strip() for x in os.getenv("CATALOG_COLLECTIONS","rings,sets-necklace-sets,tops-earrings,bangles-bracelets,pendants,monthly-sale,annual-sale").split(",") if x.strip()]
cloudinary.config(cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME",""),api_key=os.getenv("CLOUDINARY_API_KEY",""),api_secret=os.getenv("CLOUDINARY_API_SECRET",""),secure=True)
PROCESSED=set(); PROCESSING=set(); USER_SESSIONS={}
HERITAGE_PROMPT="""You are Heritage Jewelry Design Director for Heritage Jewellers. Expert in Pakistani, South Asian, Mughal-inspired, bridal, kundan, meenakari, jadau, intricate kaam, gold, silver, moissanite, lab diamond, ruby, emerald, sapphire, pearls and colored-stone jewelry. Never create generic Western minimalist jewelry. Manager approval required before customer sharing."""
COMMAND_HELP="""/stone ruby|emerald|sapphire|yellow sapphire|topaz|amethyst|pearl
/polish white gold|yellow gold|rose gold|silver
/model | /model closeup | /model 3 options
/similar | /similar earrings | /similar ring | /similar necklace | /similar bangle
/more
/alternatives
/upsell
/refreshcatalog
/caption
/product
/cad
/bridal
/collection"""
STONE_PROFILES={"ruby":("deep pigeon-blood ruby red",False),"rubi":("deep pigeon-blood ruby red",False),"laal":("deep pigeon-blood ruby red",False),"red":("deep pigeon-blood ruby red",False),"emerald":("deep Colombian emerald green",False),"zamurd":("deep Colombian emerald green",False),"zamarud":("deep Colombian emerald green",False),"panna":("deep Colombian emerald green",False),"green":("deep Colombian emerald green",False),"blue sapphire":("royal dark blue Kashmir sapphire",False),"sapphire":("royal dark blue Kashmir sapphire",False),"neelam":("royal dark blue Kashmir sapphire",False),"blue":("royal dark blue Kashmir sapphire",False),"yellow sapphire":("rich golden pukhraj yellow sapphire",False),"pukhraj":("rich golden pukhraj yellow sapphire",False),"yellow":("rich golden pukhraj yellow sapphire",False),"topaz":("Swiss blue topaz",False),"amethyst":("deep royal purple amethyst",False),"jamunia":("deep royal purple amethyst",False),"falsa":("dark blackberry purple amethyst tone",False),"champagne":("warm champagne golden-brown gemstone",False),"garnet":("deep wine-red garnet",False),"aqeeq":("deep wine-red garnet",False),"turquoise":("natural turquoise blue-green",False),"firoza":("natural turquoise blue-green",False),"morganite":("soft peach-pink morganite",False),"onyx":("deep black onyx",False),"black":("deep black onyx",False),"pearl":("smooth white pearl with natural pearl luster",True),"moti":("smooth white pearl with natural pearl luster",True),"white pearl":("smooth white pearl with natural pearl luster",True),"grey pearl":("smooth grey pearl with natural pearl luster",True),"gray pearl":("smooth grey pearl with natural pearl luster",True),"pink pearl":("smooth pink pearl with natural pearl luster",True),"black pearl":("smooth black pearl with natural pearl luster",True),"champagne pearl":("smooth champagne pearl with natural pearl luster",True)}
CATEGORY_ALIASES={"earrings":["earring","earrings","tops","stud","studs","jhumka","bali","chandbali"],"rings":["ring","rings","finger"],"necklaces":["necklace","necklaces","set","sets","haar","choker","rani haar","satlada"],"pendants":["pendant","pendants","locket"],"bangles":["bangle","bangles","bracelet","bracelets","kara","wrist"]}

def log_event(d):
    try: open(LOG_FILE,"a",encoding="utf-8").write(json.dumps(d,ensure_ascii=False)+"\n")
    except Exception as e: print("LOG_ERROR",str(e),flush=True)

def wa_text(to,body):
    r=requests.post(f"https://graph.facebook.com/v20.0/{WHATSAPP_PHONE_ID}/messages",headers={"Authorization":f"Bearer {WHATSAPP_TOKEN}","Content-Type":"application/json"},json={"messaging_product":"whatsapp","to":to,"type":"text","text":{"preview_url":False,"body":body[:4096]}},timeout=30)
    print("WA_TEXT_SEND",r.status_code,r.text[:500],flush=True); return r

def wa_image(to,img,caption=""):
    r=requests.post(f"https://graph.facebook.com/v20.0/{WHATSAPP_PHONE_ID}/messages",headers={"Authorization":f"Bearer {WHATSAPP_TOKEN}","Content-Type":"application/json"},json={"messaging_product":"whatsapp","to":to,"type":"image","image":{"link":img,"caption":caption[:1024]}},timeout=30)
    print("WA_IMAGE_SEND",r.status_code,r.text[:500],flush=True); return r

def get_media_url(mid):
    r=requests.get(f"https://graph.facebook.com/v20.0/{mid}",headers={"Authorization":f"Bearer {WHATSAPP_TOKEN}"},timeout=30); r.raise_for_status(); return r.json().get("url")
def download_media(url):
    r=requests.get(url,headers={"Authorization":f"Bearer {WHATSAPP_TOKEN}"},timeout=90); r.raise_for_status(); return r.content,r.headers.get("Content-Type","application/octet-stream")
def upload_cloudinary(b,resource_type="image"):
    return cloudinary.uploader.upload(BytesIO(b),resource_type=resource_type,folder="heritage-ai-designer")["secure_url"]
def prepare_png(b,max_side=1600):
    img=Image.open(BytesIO(b)).convert("RGBA")
    if max(img.size)>max_side: img.thumbnail((max_side,max_side))
    out=BytesIO(); img.save(out,format="PNG"); out.seek(0); out.name="heritage_input.png"; return out
def requested_stone(text):
    t=(text or "").lower()
    for k in sorted(STONE_PROFILES,key=len,reverse=True):
        if k in t: return k,STONE_PROFILES[k][0],STONE_PROFILES[k][1]
    return "ruby",STONE_PROFILES["ruby"][0],False
def requested_polish(text):
    t=(text or "").lower()
    if "white" in t: return "white gold polish, cool bright luxury white metal"
    if "rose" in t: return "rose gold polish, warm pink luxury metal"
    if "silver" in t: return "silver polish, bright cool silver tone"
    return "yellow gold polish, rich warm yellow gold tone"
def requested_category(text):
    t=(text or "").lower()
    for cat,aliases in CATEGORY_ALIASES.items():
        if any(a in t for a in aliases): return cat
    return ""

def openai_text(text,img=None,mime="image/jpeg",instructions=HERITAGE_PROMPT):
    c=OpenAI(api_key=OPENAI_API_KEY)
    content=[{"type":"input_text","text":f"Staff message: {text}\n\nCommands:\n{COMMAND_HELP}"}]
    if img:
        content.append({"type":"input_image","image_url":f"data:{mime};base64,{base64.b64encode(img).decode()}"})
    return c.responses.create(model=OPENAI_MODEL,instructions=instructions,input=[{"role":"user","content":content}]).output_text
def image_edit(img,prompt):
    c=OpenAI(api_key=OPENAI_API_KEY)
    res=c.images.edit(model=OPENAI_IMAGE_MODEL,image=prepare_png(img),prompt=prompt,size="1024x1024",n=1)
    return base64.b64decode(res.data[0].b64_json)
def product_lock(img,mime,text):
    return openai_text(text,img,mime,"""You are a strict Heritage jewelry product inspector. Return compact lock sheet: product type, main item, stone zones (main/side/drops/bunches/pearls/white stones), stone shapes, prongs, metal, chain/hook/bail/clasp/lock, motif direction, symmetry, exact parts that must not change. Do not be creative.""")
def stone_analysis(img,mime,text):
    raw=openai_text(text,img,mime,"""Return JSON only. Analyze stone zones. Fields: needs_clarification boolean, question, main_stones, side_stones, drops, bunches, pearls, white_stones, recommended_default. Clarify if multiple colored zones exist.""")
    try:
        m=re.search(r"\{.*\}",raw,re.S); return json.loads(m.group(0) if m else raw)
    except Exception: return {"needs_clarification":False}
def stone_edit(img,mime,text):
    _,profile,_=requested_stone(text); lock=product_lock(img,mime,text); low=text.lower()
    zone="all relevant mounted colored gemstones"
    if any(x in low for x in ["big","main","center","centre"]): zone="main large/center stones only"
    elif any(x in low for x in ["all","all color","all coloured","all stones"]): zone="all mounted colored stones"
    elif "drop" in low: zone="drops only"
    elif "bunch" in low: zone="bunches only"
    prompt=f"""Edit this jewelry photo for Heritage Jewellers.
TASK: Change ONLY {zone} inside the MAIN jewelry product to {profile}.
PRODUCT LOCK SHEET: {lock}
CRITICAL GEOMETRY LOCK:
Do NOT redesign or regenerate jewelry. Do NOT change stone shape, size, cut, count, position, orientation, table size, depth, prongs, bezels, side design, motifs, drops, bunches, pearl positions, chain, bail, clasp, lock, hook, polish, angle, background, or outline.
Emerald cut stays emerald cut. Oval stays oval. Baguette stays baguette. Pear stays pear.
Edit only stones physically mounted inside main jewelry. Ignore loose stones, props, chair, showcase, tray, tags, box, hands, skin, ear, neck, hair, model, dummy, wall, floor, shadows and reflections.
Do not edit diamonds, zircon, CZ, moissanite or white halo stones unless user explicitly asked all stones.
Pearl rules: pearl-to-pearl keeps smooth pearl; pearl-to-gem becomes faceted in same setting; gemstone-to-pearl becomes smooth pearl same size/position.
Use dark luxury realistic gemstone tone. Preserve facets, transparency, highlights, shadows and depth. No painted look. Return only edited image."""
    return image_edit(img,prompt)
def polish_edit(img,mime,text):
    polish=requested_polish(text); lock=product_lock(img,mime,text)
    return image_edit(img,f"""Edit this jewelry photo for Heritage Jewellers. TASK: Change ONLY metal polish to {polish}. PRODUCT LOCK SHEET: {lock}. Edit only metal. Do not edit gemstones, pearls, diamonds, zircons, CZ, moissanite, skin, background, box, tag, chair, showcase, cloth, shadows. Preserve design, stones, prongs, chain, bail, clasp, lock, angle. Return only edited image.""")
def model_edit_multi(img,mime,text):
    lock=product_lock(img,mime,text); count=3 if any(x in text.lower() for x in ["3","three","options"]) else 2
    base=f"""Create customer-shareable Heritage Jewellers model visualization.
UPLOADED JEWELRY IS MASTER REFERENCE. PRODUCT LOCK SHEET: {lock}
ABSOLUTE PRODUCT LOCK: same uploaded jewelry only. Do not redesign. Do not change stone count, stone shape, stone color, diamond layout, metal color, polish, chain, bail, clasp, hook, lock, fitting, size ratio, dimensions, motif direction, proportions. Do not add/remove components.
If earrings: show on ear only. If ring: one finger only, never two-finger ring. Pendant/necklace: neck. Bangle/bracelet: wrist.
Scale lock: realistic physical scale. Modesty lock: Pakistani/South Asian model, elegant modest formal/bridal styling, no deep neckline, no revealing outfit. Jewelry hero. Realistic contact shadows. No text/logo."""
    prompts=[base+"\nVIEW 1 close-up placement view.",base+"\nVIEW 2 styled South Asian model portrait."]
    if count>=3: prompts.append(base+"\nVIEW 3 luxury campaign/banner angle.")
    return [image_edit(img,p) for p in prompts]

# Catalog / similar
def norm(url):
    if not url: return ""
    if url.startswith("//"): return "https:"+url
    if url.startswith("/"): return HERITAGE_SITE+url
    return url
def fetch(url):
    return requests.get(url,headers={"User-Agent":"Mozilla/5.0 HeritageAI/1.0"},timeout=30).text
def extract_price(txt):
    m=re.search(r"Rs\.?\s*[\d,]+(?:\.\d+)?",txt or "",re.I); return m.group(0) if m else ""
def extract_code(txt,url=""):
    m=re.findall(r"\b[A-Z]{1,4}[-\s]?\d{2,5}\b",txt or "")
    if m: return m[0].replace(" ","")
    return url.rstrip("/").split("/")[-1][:20].upper()
def cat_from(url,title=""):
    s=(url+" "+title).lower()
    if "ring" in s: return "rings"
    if any(x in s for x in ["earring","tops","stud","jhumka"]): return "earrings"
    if any(x in s for x in ["necklace","set","choker","haar"]): return "necklaces"
    if "pendant" in s or "locket" in s: return "pendants"
    if any(x in s for x in ["bangle","bracelet","kara"]): return "bangles"
    return ""
def collect_links():
    links=set()
    for col in CATALOG_COLLECTIONS:
        for page in range(1,8):
            try:
                soup=BeautifulSoup(fetch(f"{HERITAGE_SITE}/collections/{col}?page={page}"),"html.parser")
                got=set()
                for a in soup.find_all("a",href=True):
                    if "/products/" in a["href"]: got.add(norm(a["href"].split("?")[0]))
                if not got: break
                links|=got
                if len(links)>=CATALOG_MAX_PRODUCTS: return list(links)[:CATALOG_MAX_PRODUCTS]
            except Exception as e:
                print("CATALOG_COLLECTION_ERROR",col,page,str(e),flush=True); break
    return list(links)[:CATALOG_MAX_PRODUCTS]
def parse_product(url):
    soup=BeautifulSoup(fetch(url),"html.parser")
    title=soup.find("h1").get_text(" ",strip=True) if soup.find("h1") else (soup.title.get_text(" ",strip=True) if soup.title else "")
    txt=soup.get_text(" ",strip=True); imgs=[]
    for im in soup.find_all("img"):
        src=norm(im.get("src") or im.get("data-src") or im.get("data-original"))
        if src and any(e in src.lower() for e in [".jpg",".jpeg",".png",".webp"]) and "logo" not in src.lower() and src not in imgs: imgs.append(src)
    return {"code":extract_code(title+" "+txt[:500],url),"title":title,"price":extract_price(txt),"url":url,"image":imgs[0] if imgs else "","images":imgs[:5],"category":cat_from(url,title),"description":txt[:1200],"visual_tags":title+" "+txt[:800],"visual_json":{}}
def public_image(url):
    r=requests.get(url,headers={"User-Agent":"Mozilla/5.0"},timeout=30); r.raise_for_status(); return r.content,r.headers.get("Content-Type","image/jpeg")
def analyze_product(p):
    if not CATALOG_ANALYZE_IMAGES or not p.get("image"): return p
    try:
        b,m=public_image(p["image"])
        raw=openai_text("Analyze website product image visually for similarity tags.",b,m,"""Return compact JSON only: category, workmanship, design_family, motifs, silhouette, stone_layout, pearl_layout, drops, bunches, metal, visual_keywords. Do not rely on title/code. Stone color low priority.""")
        p["visual_tags"]=raw[:2000]
        try:
            mm=re.search(r"\{.*\}",raw,re.S); p["visual_json"]=json.loads(mm.group(0) if mm else raw)
        except Exception: pass
    except Exception as e: print("CATALOG_ANALYZE_ERROR",p.get("url"),str(e),flush=True)
    return p
def load_catalog():
    try: return json.load(open(CATALOG_FILE,"r",encoding="utf-8"))
    except Exception: return {"updated_at":"","products":[]}
def save_catalog(products):
    json.dump({"updated_at":datetime.now(timezone.utc).isoformat(),"products":products},open(CATALOG_FILE,"w",encoding="utf-8"),ensure_ascii=False,indent=2)
def refresh_catalog():
    if getattr(refresh_catalog,"running",False): return
    refresh_catalog.running=True
    try:
        print("CATALOG_REFRESH_START",flush=True); products=[]
        for i,link in enumerate(collect_links(),1):
            try:
                p=analyze_product(parse_product(link)); products.append(p); print("CATALOG_PRODUCT",i,p.get("code"),flush=True)
            except Exception as e: print("CATALOG_PRODUCT_ERROR",link,str(e),flush=True)
        save_catalog(products); print("CATALOG_REFRESH_DONE",len(products),flush=True)
    finally: refresh_catalog.running=False
def auto_refresh():
    time.sleep(10)
    while True:
        try:
            data=load_catalog(); needs=not data.get("products")
            if not needs:
                try:
                    last=datetime.fromisoformat(data.get("updated_at")); needs=(datetime.now(timezone.utc)-last).total_seconds()/3600>=CATALOG_REFRESH_HOURS
                except Exception: needs=True
            if needs: refresh_catalog()
        except Exception as e: print("CATALOG_AUTO_ERROR",str(e),flush=True)
        time.sleep(3600)
def analyze_query(img,mime,text):
    raw=openai_text(text,img,mime,"""Return compact JSON for visual product matching: category, workmanship, kaam, design_family, motifs, silhouette, stone_layout, pearl_layout, drops, bunches, metal, visual_keywords. Ignore stone color as primary.""")
    try:
        m=re.search(r"\{.*\}",raw,re.S); return json.loads(m.group(0) if m else raw),raw
    except Exception: return {"visual_keywords":raw},raw
def toks(s):
    stop={"and","the","with","for","this","that","gold","silver","heritage","jewellers"}
    return {t for t in re.sub(r"[^a-z0-9\s]+"," ",(s or "").lower()).split() if len(t)>2 and t not in stop}
DESIGN={"jadau","kundan","meenakari","intricate","filigree","jaali","paisley","floral","flower","leaf","mughal","arch","chandbali","choker","satlada","haar","drops","drop","bunch","bunches","pearl","halo","cluster","teardrop","oval","baguette","emerald","cushion","round"}
def score(qobj,qraw,p,reqcat=""):
    q=toks(json.dumps(qobj)+" "+qraw); pt=toks(json.dumps(p.get("visual_json",{}))+" "+p.get("visual_tags","")+" "+p.get("description",""))
    if reqcat and p.get("category")!=reqcat: return -1
    sc=len(q&pt)*2+len((q&pt)&DESIGN)*8
    if reqcat: sc+=40
    elif p.get("category") and p.get("category") in (qobj.get("category","").lower()): sc+=25
    if p.get("image"): sc+=5
    return sc
def send_result_page(sender):
    sess=USER_SESSIONS.get(sender)
    if not sess or not sess.get("results"): wa_text(sender,"No previous similar search found. Send product image with /similar first."); return
    page=sess.get("page",0); res=sess["results"]; subset=res[page*5:page*5+5]
    if not subset: wa_text(sender,"No more options available."); return
    for item in subset:
        cap=f"Code: {item.get('code','N/A')}\nPrice: {item.get('price','N/A')}\nSimilarity: {item.get('similarity',0)}%\n\nReason:\n{item.get('reason','Similar Heritage design language.')}\n\nProduct:\n{item.get('url','')}"
        if item.get("image"): wa_image(sender,item["image"],cap)
        else: wa_text(sender,cap)
    sess["page"]=page+1; USER_SESSIONS[sender]=sess
    wa_text(sender,'Reply "more" for next 5 options.' if page*5+5<len(res) else "These are all matching options found.")
def similar_search(sender,text,img,mime,mode="similar"):
    products=load_catalog().get("products",[])
    if not products:
        wa_text(sender,"Catalog is empty. Refreshing Heritage website catalog now. Please try /similar again in a few minutes.")
        threading.Thread(target=refresh_catalog,daemon=True).start(); return
    req=requested_category(text); qobj,qraw=analyze_query(img,mime,text)
    scored=[(score(qobj,qraw,p,req),p) for p in products]; scored=[x for x in scored if x[0]>=0]; scored.sort(reverse=True,key=lambda x:x[0])
    top=scored[0][0] if scored else 1; results=[]
    for sc,p in scored:
        pp=dict(p); pp["similarity"]=max(1,min(98,int(sc/max(1,top)*96))); pp["reason"]="Similar design DNA, workmanship/kaam, motif structure and silhouette. Stone colour is secondary."; results.append(pp)
    USER_SESSIONS[sender]={"results":results,"page":0,"query":text,"category":req,"mode":mode}; send_result_page(sender)

def content_command(text,img=None,mime="image/jpeg"):
    low=text.lower()
    tasks={"/caption":"Write premium Instagram caption, short version, long version, hashtags.","/product":"Write website title, short description, full description, styling notes, SEO keywords.","/cad":"Write CAD/manufacturing brief with setting, construction, stone placement, comfort, production notes.","/bridal":"Create Heritage bridal version concept preserving design DNA.","/collection":"Create matching Heritage collection: earrings, pendant, ring, bracelet/bangle, necklace."}
    task=next((v for k,v in tasks.items() if low.startswith(k)),"Answer as Heritage Jewelry Design Director.")
    return openai_text(f"{text}\n\nTask: {task}",img,mime)

def background_job(sender,text,img,mime,msgid):
    try:
        print("BACKGROUND_JOB_START",msgid,sender,text[:100],flush=True); low=text.lower().strip()
        if low.startswith("/stone"):
            if not any(x in low for x in ["big","main","center","centre","all","drop","bunch"]):
                analysis=stone_analysis(img,mime,text)
                if analysis.get("needs_clarification"):
                    USER_SESSIONS[sender]={"pending_command":"stone","text":text,"image_b64":base64.b64encode(img).decode(),"image_mime":mime}
                    wa_text(sender,(analysis.get("question") or "I detected multiple stone zones.")+"\n\n1️⃣ Main stones only\n2️⃣ All colored stones\n3️⃣ Drops/bunches only\n4️⃣ Custom: type your instruction")
                    return
            out=stone_edit(img,mime,text); wa_image(sender,upload_cloudinary(out),"Heritage stone edit. Manager approval required before customer sharing.")
        elif low.startswith("/polish"):
            out=polish_edit(img,mime,text); wa_image(sender,upload_cloudinary(out),"Heritage polish edit. Manager approval required before customer sharing.")
        elif low.startswith("/model"):
            for i,out in enumerate(model_edit_multi(img,mime,text),1): wa_image(sender,upload_cloudinary(out),f"Heritage model visualization option {i}. Manager approval required before customer sharing.")
        elif low.startswith("/similar") or low.startswith("/alternatives") or low.startswith("/upsell"):
            similar_search(sender,text,img,mime,mode=low.split()[0].replace("/",""))
        else:
            wa_text(sender,content_command(text,img,mime)+"\n\nManager approval required before customer sharing.")
        PROCESSED.add(msgid); print("BACKGROUND_JOB_DONE",msgid,flush=True)
    except Exception as e:
        print("BACKGROUND_JOB_ERROR",str(e),flush=True); wa_text(sender,f"Sorry, Heritage AI had an error: {str(e)[:700]}")
    finally: PROCESSING.discard(msgid)

@app.route("/",methods=["GET"])
def home(): return "Heritage WhatsApp AI Designer V4 backend is running.",200
@app.route("/health",methods=["GET"])
def health():
    d=load_catalog(); return jsonify({"status":"ok","catalog_products":len(d.get("products",[])),"catalog_updated_at":d.get("updated_at","")}),200
@app.route("/webhook",methods=["GET"])
def verify():
    if request.args.get("hub.mode")=="subscribe" and request.args.get("hub.verify_token")==VERIFY_TOKEN: return request.args.get("hub.challenge") or "",200
    return "Verification failed",403
@app.route("/webhook",methods=["POST"])
def webhook():
    payload=request.get_json(silent=True) or {}; log_event({"time":datetime.now(timezone.utc).isoformat(),"payload":payload})
    try:
        value=payload.get("entry",[])[0].get("changes",[])[0].get("value",{})
        if "statuses" in value: return jsonify({"status":"status_update"}),200
        msgs=value.get("messages",[])
        if not msgs: return jsonify({"status":"ignored"}),200
        msg=msgs[0]; msgid=msg.get("id","")
        if msgid in PROCESSED or msgid in PROCESSING: return jsonify({"status":"duplicate_ignored"}),200
        sender=msg.get("from")
        if STAFF_NUMBERS and sender not in STAFF_NUMBERS:
            wa_text(sender,"Access denied. This Heritage AI Designer number is staff-only."); return jsonify({"status":"blocked"}),200
        text=""; img=None; mime="image/jpeg"
        if msg.get("type")=="text": text=msg.get("text",{}).get("body","").strip()
        elif msg.get("type")=="image":
            text=msg.get("image",{}).get("caption","").strip(); mid=msg.get("image",{}).get("id")
            if mid: img,mime=download_media(get_media_url(mid))
        elif msg.get("type")=="video":
            wa_text(sender,"Video received. V4 video frame extraction is under development. For now, please send the clearest product image for /stone, /model or /similar."); return jsonify({"status":"video_received"}),200
        else:
            wa_text(sender,"Please send text or image with caption. Example: /stone ruby or /similar earrings"); return jsonify({"status":"unsupported"}),200
        low=text.lower().strip()
        if low in ["more","/more"]:
            send_result_page(sender); PROCESSED.add(msgid); return jsonify({"status":"more_sent"}),200
        sess=USER_SESSIONS.get(sender,{})
        if sess.get("pending_command")=="stone" and not img:
            old=base64.b64decode(sess.get("image_b64")); oldmime=sess.get("image_mime","image/jpeg"); oldtext=sess.get("text","/stone ruby")
            if low.startswith("1"): new=oldtext+" main stones only"
            elif low.startswith("2"): new=oldtext+" all colored stones"
            elif low.startswith("3"): new=oldtext+" drops and bunches only"
            else: new=oldtext+" "+text
            USER_SESSIONS.pop(sender,None); PROCESSING.add(msgid); wa_text(sender,f"Understood: {new}. Editing now...")
            threading.Thread(target=background_job,args=(sender,new,old,oldmime,msgid),daemon=True).start(); return jsonify({"status":"clarification_processing"}),200
        if low.startswith("/refreshcatalog"):
            if MANAGER_NUMBERS and sender not in MANAGER_NUMBERS: wa_text(sender,"Only manager numbers can refresh catalog.")
            else:
                wa_text(sender,"Refreshing Heritage website catalog in background. This may take a few minutes."); threading.Thread(target=refresh_catalog,daemon=True).start()
            PROCESSED.add(msgid); return jsonify({"status":"refresh_started"}),200
        if not text: text="Analyze this jewelry image for Heritage Jewellers."; low=text.lower()
        image_cmd=any(low.startswith(c) for c in ["/stone","/polish","/model","/similar","/alternatives","/upsell"])
        if image_cmd and not img:
            wa_text(sender,"Please send this command with a product image."); PROCESSED.add(msgid); return jsonify({"status":"image_required"}),200
        if img and image_cmd:
            PROCESSING.add(msgid)
            if low.startswith("/stone"): wa_text(sender,"Analyzing stone zones and editing mounted jewelry stones only. Please wait...")
            elif low.startswith("/polish"): wa_text(sender,"Editing metal polish only. Please wait...")
            elif low.startswith("/model"): wa_text(sender,"Creating Heritage model visualization options. Please wait...")
            else: wa_text(sender,"Searching Heritage website for visually similar products. Please wait...")
            threading.Thread(target=background_job,args=(sender,text,img,mime,msgid),daemon=True).start(); return jsonify({"status":"processing_started"}),200
        wa_text(sender,content_command(text,img,mime)+"\n\nManager approval required before customer sharing."); PROCESSED.add(msgid); return jsonify({"status":"ok"}),200
    except Exception as e:
        print("WEBHOOK_ERROR",str(e),flush=True)
        try: wa_text(payload["entry"][0]["changes"][0]["value"]["messages"][0]["from"],f"Sorry, Heritage AI had an error: {str(e)[:700]}")
        except Exception: pass
        return jsonify({"status":"error"}),200

threading.Thread(target=auto_refresh,daemon=True).start()
if __name__=="__main__": app.run(host="0.0.0.0",port=int(os.getenv("PORT","10000")))

