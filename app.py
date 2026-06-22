
import os, json, base64, requests, threading
from io import BytesIO
from datetime import datetime, timezone
from flask import Flask, request, jsonify
from openai import OpenAI
from PIL import Image, ImageFilter
import cloudinary, cloudinary.uploader

app = Flask(__name__)

VERIFY_TOKEN=os.getenv("VERIFY_TOKEN","heritage_verify_123")
WHATSAPP_TOKEN=os.getenv("WHATSAPP_TOKEN","")
WHATSAPP_PHONE_ID=os.getenv("WHATSAPP_PHONE_ID","")
OPENAI_API_KEY=os.getenv("OPENAI_API_KEY","")
OPENAI_MODEL=os.getenv("OPENAI_MODEL","gpt-4.1-mini")
OPENAI_IMAGE_MODEL=os.getenv("OPENAI_IMAGE_MODEL","gpt-image-1")
STAFF_NUMBERS=[x.strip() for x in os.getenv("STAFF_NUMBERS","").split(",") if x.strip()]
LOG_FILE=os.getenv("LOG_FILE","logs.jsonl")

cloudinary.config(
    cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME",""),
    api_key=os.getenv("CLOUDINARY_API_KEY",""),
    api_secret=os.getenv("CLOUDINARY_API_SECRET",""),
    secure=True,
)

PROCESSED=set()
PROCESSING=set()

HERITAGE_PROMPT = """
You are Heritage Jewelry Design Director for Heritage Jewellers.
Expert in Pakistani, South Asian, Mughal-inspired, bridal, kundan, meenakari,
gold, silver, moissanite, lab diamond, emerald, ruby, sapphire, topaz, amethyst,
tourmaline, tanzanite, pearls and colored-stone jewelry.
Never create generic Western minimalist jewelry.
Manager approval required before customer sharing.
"""

COMMAND_HELP = """/stone ruby, emerald, sapphire, yellow sapphire, topaz, amethyst, champagne, pearl
/polish yellow gold, white gold, rose gold, silver
/model, /model closeup, /model bridal, /model 3 options
/caption
/product
/cad
/bridal
/collection"""


def log_event(data):
    try:
        with open(LOG_FILE,"a",encoding="utf-8") as f:
            f.write(json.dumps(data,ensure_ascii=False)+"\n")
    except Exception as e:
        print("LOG_ERROR",e,flush=True)


def wa_text(to, body):
    url=f"https://graph.facebook.com/v20.0/{WHATSAPP_PHONE_ID}/messages"
    headers={"Authorization":f"Bearer {WHATSAPP_TOKEN}","Content-Type":"application/json"}
    payload={"messaging_product":"whatsapp","to":to,"type":"text","text":{"preview_url":False,"body":body[:4096]}}
    r=requests.post(url,headers=headers,json=payload,timeout=30)
    print("WA_TEXT_SEND",r.status_code,r.text[:500],flush=True)
    return r


def wa_image(to, image_url, caption=""):
    url=f"https://graph.facebook.com/v20.0/{WHATSAPP_PHONE_ID}/messages"
    headers={"Authorization":f"Bearer {WHATSAPP_TOKEN}","Content-Type":"application/json"}
    payload={"messaging_product":"whatsapp","to":to,"type":"image","image":{"link":image_url,"caption":caption[:1024]}}
    r=requests.post(url,headers=headers,json=payload,timeout=30)
    print("WA_IMAGE_SEND",r.status_code,r.text[:500],flush=True)
    return r


def get_media_url(media_id):
    r=requests.get(f"https://graph.facebook.com/v20.0/{media_id}",headers={"Authorization":f"Bearer {WHATSAPP_TOKEN}"},timeout=30)
    r.raise_for_status()
    return r.json().get("url")


def download_media(media_url):
    r=requests.get(media_url,headers={"Authorization":f"Bearer {WHATSAPP_TOKEN}"},timeout=60)
    r.raise_for_status()
    return r.content, r.headers.get("Content-Type","image/jpeg")


def upload_cloudinary(image_bytes):
    result=cloudinary.uploader.upload(BytesIO(image_bytes),resource_type="image",folder="heritage-ai-designer")
    return result["secure_url"]


def png_bytes(img):
    out=BytesIO()
    img.save(out,format="PNG")
    return out.getvalue()


def norm(text):
    return (text or "").lower().replace("-"," ").replace("_"," ")


def wants_all_stones(text):
    t=norm(text)
    return any(k in t for k in ["all stones","small stones","all","sab","saray","zircon also"])


def target_profile(text):
    t=norm(text)
    vocab=[
        (["yellow sapphire","pukhraj","peela","yellow"],"yellow_sapphire"),
        (["blue sapphire","sapphire","neelam","blue"],"sapphire"),
        (["pink sapphire"],"pink_sapphire"),
        (["emerald","zamurd","zamarud","panna","green"],"emerald"),
        (["ruby","rubi","laal","red"],"ruby"),
        (["swiss blue topaz","sky blue topaz","topaz"],"topaz"),
        (["champagne"],"champagne"),
        (["amethyst","jamunia","falsa","purple"],"amethyst"),
        (["garnet","aqeeq"],"garnet"),
        (["turquoise","firoza","feroza"],"turquoise"),
        (["aquamarine"],"aquamarine"),
        (["citrine"],"citrine"),
        (["peridot","zabarjad","zabarjid"],"peridot"),
        (["tanzanite"],"tanzanite"),
        (["tourmaline"],"tourmaline"),
        (["morganite"],"morganite"),
        (["black pearl","black moti"],"black_pearl"),
        (["grey pearl","gray pearl","grey moti"],"grey_pearl"),
        (["pink pearl","pink moti"],"pink_pearl"),
        (["champagne pearl"],"champagne_pearl"),
        (["white pearl","pearl","moti"],"white_pearl"),
        (["onyx","black"],"onyx"),
    ]
    for keys,name in vocab:
        if any(k in t for k in keys):
            return name
    return "ruby"


STONE_HUE={
    "ruby":250,"garnet":248,"emerald":92,"sapphire":160,"yellow_sapphire":38,
    "pink_sapphire":225,"topaz":140,"champagne":30,"amethyst":190,"turquoise":125,
    "aquamarine":135,"citrine":34,"peridot":78,"tanzanite":175,"tourmaline":218,
    "morganite":18,"onyx":"black",
}


def is_pearl_target(profile):
    return profile.endswith("_pearl")


def is_skin(r,g,b):
    return r>70 and g>35 and b>20 and r>g>=b and (r-g)<115 and (g-b)<100


def is_bg(r,g,b):
    return (r>220 and g>220 and b>220) or (abs(r-g)<14 and abs(g-b)<14 and r>165)


def is_gold(r,g,b):
    return r>112 and g>68 and b<118 and r>b*1.18 and g>b*0.82


def is_white_stone_or_silver(r,g,b):
    mx=max(r,g,b); mn=min(r,g,b)
    return mx>135 and (mx-mn)<62


def is_jewelry_support(r,g,b):
    if is_skin(r,g,b) or is_bg(r,g,b):
        return False
    return is_gold(r,g,b) or is_white_stone_or_silver(r,g,b)


def is_pearl_pixel(r,g,b):
    mx=max(r,g,b); mn=min(r,g,b)
    return mx>105 and (mx-mn)<55 and not is_bg(r,g,b) and not is_skin(r,g,b)


def is_colored_stone(r,g,b,text):
    if is_skin(r,g,b) or is_bg(r,g,b) or is_jewelry_support(r,g,b):
        return False
    mx=max(r,g,b); mn=min(r,g,b); c=mx-mn
    if c<24 or mx<32:
        return False
    green=g>r*0.58 and g>b*0.82 and g>35
    red=r>g*1.04 and r>b*0.98 and r>50 and g<185
    pink=r>80 and b>45 and r>g*1.02 and b>g*0.65
    blue=b>r*0.90 and b>g*0.86 and b>40
    yellow=r>95 and g>80 and b<90 and abs(r-g)<80
    purple=b>60 and r>60 and g<max(r,b)*0.82
    return green or red or pink or blue or yellow or purple


def build_mask(rgb,text,include_pearls=False):
    w,h=rgb.size; px=rgb.load()
    mask=[[False]*w for _ in range(h)]
    for y in range(h):
        for x in range(w):
            r,g,b=px[x,y]
            if is_colored_stone(r,g,b,text) or (include_pearls and is_pearl_pixel(r,g,b)):
                mask[y][x]=True
    return mask


def components(mask):
    h=len(mask); w=len(mask[0]); seen=[[False]*w for _ in range(h)]; comps=[]
    for y in range(h):
        for x in range(w):
            if not mask[y][x] or seen[y][x]: continue
            stack=[(x,y)]; seen[y][x]=True; pts=[]
            while stack:
                cx,cy=stack.pop(); pts.append((cx,cy))
                for nx,ny in ((cx+1,cy),(cx-1,cy),(cx,cy+1),(cx,cy-1)):
                    if 0<=nx<w and 0<=ny<h and mask[ny][nx] and not seen[ny][nx]:
                        seen[ny][nx]=True; stack.append((nx,ny))
            comps.append(pts)
    return comps


def support_ratio(points,rgb,pad=18):
    w,h=rgb.size; px=rgb.load()
    xs=[p[0] for p in points]; ys=[p[1] for p in points]
    x1,x2=min(xs),max(xs); y1,y2=min(ys),max(ys)
    sx1,sy1=max(0,x1-pad),max(0,y1-pad); sx2,sy2=min(w-1,x2+pad),min(h-1,y2+pad)
    total=support=0
    for y in range(sy1,sy2+1,2):
        for x in range(sx1,sx2+1,2):
            total+=1
            r,g,b=px[x,y]
            if is_jewelry_support(r,g,b): support+=1
    return support/max(total,1)


def comp_score(points,rgb,allow_small=False):
    w,h=rgb.size; area=len(points)
    xs=[p[0] for p in points]; ys=[p[1] for p in points]
    x1,x2=min(xs),max(xs); y1,y2=min(ys),max(ys)
    bw=max(1,x2-x1+1); bh=max(1,y2-y1+1)
    fill=area/float(bw*bh); aspect=max(bw/bh,bh/bw)
    if x1<=2 or y1<=2 or x2>=w-3 or y2>=h-3: return 0
    if area < (10 if allow_small else 20): return 0
    if aspect>9 or fill<0.04: return 0
    sup=support_ratio(points,rgb)
    if sup<0.022: return 0
    return area*(1+sup*10)


def refined_stone_mask(rgb,text,include_pearls=False):
    w,h=rgb.size; max_side=max(w,h)
    if max_side>900:
        scale=900/max_side; small=rgb.resize((int(w*scale),int(h*scale)))
    else:
        scale=1.0; small=rgb
    raw=build_mask(small,text,include_pearls)
    scored=[]
    for c in components(raw):
        s=comp_score(c,small,allow_small=wants_all_stones(text))
        if s>0: scored.append((s,c))
    scored.sort(reverse=True,key=lambda x:x[0])
    if not scored:
        print("STONE_MASK_COMPONENTS 0",flush=True)
        return [[False]*w for _ in range(h)]
    largest=scored[0][0]; keep=[]; min_rel=0.025 if wants_all_stones(text) else 0.07
    for score,comp in scored:
        if score>=max(10,largest*min_rel): keep.extend(comp)
    mi=Image.new("L",small.size,0); px=mi.load()
    for x,y in keep: px[x,y]=255
    mi=mi.filter(ImageFilter.MaxFilter(3)).filter(ImageFilter.GaussianBlur(0.45))
    if scale!=1.0: mi=mi.resize((w,h))
    mpx=mi.load()
    final=[[False]*w for _ in range(h)]
    for y in range(h):
        for x in range(w): final[y][x]=mpx[x,y]>95
    print("STONE_MASK_COMPONENTS",len(scored),"KEPT_PIXELS",len(keep),flush=True)
    return final


def recolor_hsv(h,s,v,profile):
    if is_pearl_target(profile):
        if profile=="grey_pearl": return h,10,min(215,max(90,int(v*1.04)))
        if profile=="pink_pearl": return 235,45,min(235,max(110,int(v*1.08)))
        if profile=="champagne_pearl": return 28,50,min(235,max(115,int(v*1.04)))
        if profile=="black_pearl": return h,20,min(90,max(28,int(v*0.45)))
        return h,12,min(242,max(125,int(v*1.1)))
    target=STONE_HUE.get(profile,250)
    if target=="black": return h,int(s*0.35),int(v*0.22)
    new_h=target; new_s=min(255,max(85,int(s*1.02))); new_v=min(235,max(18,int(v*0.82)))
    if profile in ["sapphire","amethyst","garnet","onyx"]:
        new_v=min(225,max(15,int(v*0.72))); new_s=min(255,max(105,int(s*1.12)))
    if profile in ["yellow_sapphire","champagne","citrine"]:
        new_v=min(242,max(80,int(v*0.94))); new_s=min(230,max(75,int(s*0.9)))
    if v>205:
        new_s=int(new_s*0.45); new_v=min(245,int(v*0.96))
    if v<70: new_v=int(new_v*0.78)
    return new_h,new_s,new_v


def exact_stone_change(image_bytes,text):
    profile=target_profile(text); include_pearls=is_pearl_target(profile)
    img=Image.open(BytesIO(image_bytes)).convert("RGBA")
    if max(img.size)>1400: img.thumbnail((1400,1400))
    rgb=img.convert("RGB"); hsv=rgb.convert("HSV"); alpha=img.getchannel("A")
    w,h=rgb.size; mask=refined_stone_mask(rgb,text,include_pearls)
    out=[]; changed=0
    for idx,(hh,s,v) in enumerate(list(hsv.getdata())):
        x=idx%w; y=idx//w
        if mask[y][x]:
            changed+=1; out.append(recolor_hsv(hh,s,v,profile))
        else:
            out.append((hh,s,v))
    print("STONE_PIXELS_CHANGED",changed,"PROFILE",profile,flush=True)
    hsv.putdata(out); rgb2=hsv.convert("RGB")
    return png_bytes(Image.merge("RGBA",(*rgb2.split(),alpha)).filter(ImageFilter.SHARPEN))


def polish_profile(text):
    t=norm(text)
    if "white" in t or "silver" in t: return "white"
    if "rose" in t: return "rose"
    return "yellow"


def exact_polish_change(image_bytes,text):
    prof=polish_profile(text)
    img=Image.open(BytesIO(image_bytes)).convert("RGBA")
    if max(img.size)>1400: img.thumbnail((1400,1400))
    rgb=img.convert("RGB"); hsv=rgb.convert("HSV"); alpha=img.getchannel("A")
    out=[]; changed=0
    for (r,g,b),(h,s,v) in zip(list(rgb.getdata()),list(hsv.getdata())):
        if is_gold(r,g,b) or is_white_stone_or_silver(r,g,b):
            if is_white_stone_or_silver(r,g,b) and not is_gold(r,g,b) and prof!="yellow":
                out.append((h,s,v)); continue
            changed+=1
            if prof=="white": out.append((h,18,min(245,int(v*1.05))))
            elif prof=="rose": out.append((245,min(95,max(35,int(s*0.75))),min(235,int(v*0.98))))
            else: out.append((32,min(125,max(45,int(s*0.95))),min(240,int(v*1.02))))
        else:
            out.append((h,s,v))
    print("POLISH_PIXELS_CHANGED",changed,"PROFILE",prof,flush=True)
    hsv.putdata(out); rgb2=hsv.convert("RGB")
    return png_bytes(Image.merge("RGBA",(*rgb2.split(),alpha)).filter(ImageFilter.SHARPEN))


def prepare_image_file(image_bytes):
    img=Image.open(BytesIO(image_bytes)).convert("RGBA")
    if max(img.size)>1600: img.thumbnail((1600,1600))
    out=BytesIO(); img.save(out,format="PNG"); out.seek(0); out.name="heritage_input.png"
    return out


def image_edit_ai(image_bytes,prompt):
    client=OpenAI(api_key=OPENAI_API_KEY)
    res=client.images.edit(model=OPENAI_IMAGE_MODEL,image=prepare_image_file(image_bytes),prompt=prompt,size="1024x1024",n=1)
    return base64.b64decode(res.data[0].b64_json)


def model_edit_ai(image_bytes,text):
    prompt=f"""
Create a luxury Heritage Jewellers model visualization.
Use uploaded jewelry as strict reference. Preserve same product as closely as possible:
same stone count, stone color, stone shape, polish, lock/fitting, chain, dimensions and design.
If earrings: ear close-up. If ring: hand/finger close-up. If bangle: wrist close-up. If pendant/necklace: neck close-up.
No extra jewelry. Jewelry is hero. Pakistani/South Asian luxury bridal/party styling.
Staff request: {text}
"""
    return image_edit_ai(image_bytes,prompt)


def openai_text(text,image_bytes=None,image_mime="image/jpeg"):
    client=OpenAI(api_key=OPENAI_API_KEY)
    content=[{"type":"input_text","text":f"Staff message: {text}\n\nCommands:\n{COMMAND_HELP}"}]
    if image_bytes:
        b64=base64.b64encode(image_bytes).decode("utf-8")
        content.append({"type":"input_image","image_url":f"data:{image_mime};base64,{b64}"})
    res=client.responses.create(model=OPENAI_MODEL,instructions=HERITAGE_PROMPT,input=[{"role":"user","content":content}])
    return res.output_text


def background_job(sender,text,image_bytes,image_mime,message_id):
    try:
        print("BACKGROUND_JOB_START",message_id,sender,text[:100],flush=True)
        lower=norm(text)
        if lower.startswith("/stone"):
            output=exact_stone_change(image_bytes,text); url=upload_cloudinary(output)
            wa_image(sender,url,"Stone edit. Manager approval required before customer sharing.")
        elif lower.startswith("/polish"):
            output=exact_polish_change(image_bytes,text); url=upload_cloudinary(output)
            wa_image(sender,url,"Polish edit. Manager approval required before customer sharing.")
        elif lower.startswith("/model"):
            output=model_edit_ai(image_bytes,text); url=upload_cloudinary(output)
            wa_image(sender,url,"Heritage model visualization. Manager approval required before customer sharing.")
        else:
            reply=openai_text(text,image_bytes,image_mime)+"\n\nManager approval required before customer sharing."
            wa_text(sender,reply)
        PROCESSED.add(message_id); print("BACKGROUND_JOB_DONE",message_id,flush=True)
    except Exception as e:
        print("BACKGROUND_JOB_ERROR",str(e),flush=True); wa_text(sender,f"Sorry, Heritage AI had an error: {str(e)[:700]}")
    finally:
        PROCESSING.discard(message_id)


@app.route("/",methods=["GET"])
def home():
    return "Heritage WhatsApp AI Designer backend is running.",200


@app.route("/webhook",methods=["GET"])
def verify_webhook():
    mode=request.args.get("hub.mode"); token=request.args.get("hub.verify_token"); challenge=request.args.get("hub.challenge")
    if mode=="subscribe" and token==VERIFY_TOKEN: return challenge or "",200
    return "Verification failed",403


@app.route("/webhook",methods=["POST"])
def receive_webhook():
    payload=request.get_json(silent=True) or {}
    log_event({"time":datetime.now(timezone.utc).isoformat(),"payload":payload})
    try:
        value=payload.get("entry",[])[0].get("changes",[])[0].get("value",{})
        if "statuses" in value: return jsonify({"status":"status_update"}),200
        messages=value.get("messages",[])
        if not messages: return jsonify({"status":"ignored"}),200
        msg=messages[0]; message_id=msg.get("id","")
        if message_id in PROCESSED or message_id in PROCESSING: return jsonify({"status":"duplicate_ignored"}),200
        sender=msg.get("from")
        if STAFF_NUMBERS and sender not in STAFF_NUMBERS:
            wa_text(sender,"Access denied. This Heritage AI Designer number is staff-only."); return jsonify({"status":"blocked"}),200
        text=""; image_bytes=None; image_mime="image/jpeg"
        if msg.get("type")=="text":
            text=msg.get("text",{}).get("body","")
        elif msg.get("type")=="image":
            text=msg.get("image",{}).get("caption","")
            media_id=msg.get("image",{}).get("id")
            if media_id:
                media_url=get_media_url(media_id); image_bytes,image_mime=download_media(media_url)
        else:
            wa_text(sender,"Please send text or image with caption. Example: /stone ruby"); return jsonify({"status":"unsupported"}),200
        if not text: text="Analyze this jewelry image for Heritage Jewellers."
        lower=norm(text)
        if image_bytes and (lower.startswith("/stone") or lower.startswith("/polish") or lower.startswith("/model")):
            PROCESSING.add(message_id)
            if lower.startswith("/stone"): wa_text(sender,"Editing mounted gemstones only. Please wait...")
            elif lower.startswith("/polish"): wa_text(sender,"Editing metal polish only. Please wait...")
            else: wa_text(sender,"Creating Heritage model visualization. Please wait...")
            threading.Thread(target=background_job,args=(sender,text,image_bytes,image_mime,message_id),daemon=True).start()
            return jsonify({"status":"processing_started"}),200
        reply=openai_text(text,image_bytes,image_mime)+"\n\nManager approval required before customer sharing."
        wa_text(sender,reply)
        if message_id: PROCESSED.add(message_id)
        return jsonify({"status":"ok"}),200
    except Exception as e:
        print("WEBHOOK_ERROR",str(e),flush=True)
        try:
            sender=payload["entry"][0]["changes"][0]["value"]["messages"][0]["from"]
            wa_text(sender,f"Sorry, Heritage AI had an error: {str(e)[:700]}")
        except Exception: pass
        return jsonify({"status":"error"}),200


if __name__=="__main__":
    port=int(os.getenv("PORT","10000"))
    app.run(host="0.0.0.0",port=port)
