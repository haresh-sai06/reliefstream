"""Generate a synthetic, programmatically-labelled training set for ReliefStream extraction.

Labels come from the template slots that produced each message -- they are NOT derived
from, or tuned against, eval/labeled_messages.jsonl (the 41-message TEST set).
Place names are drawn from Chennai / Madurai / Kerala / Assam / Tirunelveli localities;
any name that appears in the test set is rejected (see check_overlap.py).
"""
import json, random, sys
from pathlib import Path

R = random.Random(int(sys.argv[2]) if len(sys.argv) > 2 else 13)
N = int(sys.argv[1]) if len(sys.argv) > 1 else 600

AREAS = ["Velachery", "Tambaram", "Mudichur", "Pallikaranai", "Madipakkam", "Perumbakkam", "Semmancheri",
         "Saidapet", "Kotturpuram", "Mylapore", "Adyar", "Ashok Nagar", "KK Nagar", "Valasaravakkam",
         "Porur", "Manapakkam", "Ekkatuthangal", "Jafferkhanpet", "Vyasarpadi", "Tondiarpet", "Ennore",
         "Manali", "Thiruvottiyur", "Perambur", "Kolathur", "Ambattur", "Avadi", "Poonamallee",
         "Chromepet", "Pammal", "Anakaputhur", "Selaiyur", "Medavakkam", "Sholinganallur", "Thoraipakkam",
         "Anna Nagar West", "Arumbakkam", "Koyambedu", "Vadapalani", "West Mambalam", "Teynampet",
         "Simmakkal", "Anna Nagar Madurai", "Tallakulam", "Goripalayam", "Thirunagar", "Palayamkottai",
         "Melapalayam", "Aluva", "Chalakudy", "Paravur", "Chengannur", "Kuttanad", "Ranni", "Pandanad",
         "Silchar Tarapur", "Guwahati Anil Nagar", "Zoo Road Guwahati", "Nagaon Haibargaon", "Cuddalore OT",
         "Chidambaram", "Sirkazhi", "Nagapattinam Velipalayam", "Thoothukudi Muthammal colony", "Srivaikuntam"]
STREETS = ["{n} main road", "{n} cross street", "{n} street", "{n} avenue", "{n} lane", "block {b}",
           "{n} sector", "Gandhi street", "Nehru street", "Bharathi nagar", "Kamaraj salai", "MGR nagar",
           "Indira colony", "Periyar street", "VOC nagar", "temple street", "lake view road", "railway colony"]
LANDMARKS = ["the water tank", "Indian Oil bunk", "SBI ATM", "the bus stop", "Murugan temple", "the church",
             "St. Mary's school", "govt hospital", "the ration shop", "Aavin booth", "the post office",
             "the panchayat office", "the mosque", "the vegetable market", "the railway gate"]
ORD = ["1st", "2nd", "3rd", "4th", "5th", "6th", "7th", "9th", "10th", "11th"]
TAM_IN = ["ல", "இல்"]; TAM_NEAR = "பக்கம்"; TAM_HELP = ["உதவி பண்ணுங்க", "help pannunga", "please help"]


def phone():
    style = R.random()
    d = "".join(R.choice("0123456789") for _ in range(9))
    first = R.choice("6789")
    num = first + d
    if style < 0.35: return num
    if style < 0.6: return num[:5] + "-" + num[5:]
    if style < 0.75: return num[:5] + " " + num[5:]
    if style < 0.85: return "+91 " + num
    return num[:5] + "XXXXX"


def place():
    area = R.choice(AREAS)
    st = R.choice(STREETS).format(n=R.choice(ORD), b=R.choice("ABCDEFGH"))
    lm = R.choice(LANDMARKS)
    form = R.random()
    if form < 0.4: return f"{area} {st}", f"{area} {st}", lm
    if form < 0.7: return f"{st}, {area}", f"{area} {st}", lm
    return area, area, lm


SCEN = [  # (request_type, urgency, builder)
    ("rescue", "immediate", lambda p, c, l, k: [
        f"{p} stranded on rooftop at {l} near {k}, water rising fast, need rescue boat",
        f"{p} on terrace in {l} opposite {k}, water at first floor level, need boat immediately",
        f"URGENT {p} stuck on roof {l}, kids crying water still rising pls send rescue team"]),
    ("rescue", "high", lambda p, c, l, k: [
        f"{p} trapped inside house at {l} behind {k}, water entering ground floor, can't come out",
        f"{p} stuck in first floor {l} near {k}, no power since last night, need someone to take us out"]),
    ("medical", "immediate", lambda p, c, l, k: [
        f"Medical emergency {l} near {k}: {p} - one person unconscious, need ambulance boat now",
        f"pregnant woman in labour at {l} opposite {k}, road flooded, ambulance can't reach, {p} in house"]),
    ("medical", "high", lambda p, c, l, k: [
        f"{p} at {l}, my grandfather dialysis patient missed session, water around house, need medical help",
        f"Child with high fever 2 days {l} near {k}, no medicine, {p} in the house"]),
    ("food", "low", lambda p, c, l, k: [
        f"Food packets needed for {p} sheltered at {k}, {l}. We are safe but nothing to eat",
        f"{l} relief camp near {k}: {p} need dinner packets tonight, all safe otherwise"]),
    ("food", "high", lambda p, c, l, k: [
        f"{p} no food since yesterday morning at {l} near {k}, water all around, cannot go out"]),
    ("water", "low", lambda p, c, l, k: [
        f"Drinking water cans needed at {k} {l} for {p}, all safe in community hall",
        f"Need drinking water bottles at {l} near {k}, about {p} sheltering here"]),
    ("evacuation", "medium", lambda p, c, l, k: [
        f"{p} at {l} near {k} safe for now but water slowly rising, need to shift to relief camp",
        f"Please arrange vehicle to evacuate {p} from {l}, opposite {k}, house surrounded but we are ok now"]),
    ("shelter", "medium", lambda p, c, l, k: [
        f"{p} house collapsed partially in {l} near {k}, need place to stay tonight",
        f"Need shelter for {p} from {l}, our hut washed away, now standing near {k}"]),
]
PEOPLE = [(1, "my mother"), (2, "2 elderly people"), (2, "old couple"), (3, "3 of us"), (3, "family of 3"),
          (4, "4 members"), (4, "family of 4"), (5, "5 people"), (6, "6 people incl 2 kids"), (7, "7 people"),
          (8, "8 persons"), (10, "10 families"), (12, "12 people"), (20, "20 people"), (25, "25 people"),
          (40, "around 40 people"), (60, "60 families"), (None, "we"), (None, "people"), (None, "my family")]
NEG = [
    "Water level going down in {a} now, our volunteers already distributed food there",
    "NDRF team reached {a}, families being moved to camp, no need to send more boats",
    "{a} floods {y} was so bad, govt must plan better this time",
    "Heavy rain again tonight in {a}, stay safe everyone",
    "Breaking: IMD issues red alert for {a} district for next 48 hours",
    "Avoid {a} main road, waterlogging, take alternate route",
    "Collected 200 food packets at {a} college, volunteers with bikes please come",
    "Our team has 3 boats ready, where should we go? share locations",
    "Is the {a} subway open for vehicles now?",
    "testing testing ignore this msg",
    "Thanks to everyone who helped in {a}, all families safe now",
    "Heard a loud noise near {a} what happened",
]


def tamilize(msg, loc):
    if R.random() < 0.5:
        msg = msg.replace(f"at {loc}", f"{loc} {R.choice(TAM_IN)}").replace(f"in {loc}", f"{loc} {R.choice(TAM_IN)}")
    msg = msg.replace(" near ", f" {TAM_NEAR} ", 1) if R.random() < 0.3 else msg
    return msg + " " + R.choice(TAM_HELP)


def noisy(msg):
    r = R.random()
    if r < 0.15: msg = "Fwd: " + msg
    elif r < 0.25: msg = "*Forwarded as received* " + msg
    elif r < 0.3: msg = "RT @chennairains: " + msg
    if R.random() < 0.3: msg = msg.lower()
    if R.random() < 0.2: msg = msg.replace(",", "")
    if R.random() < 0.2: msg += R.choice([" pls share", " please forward", "!!", " 🙏"])
    return msg


def make_pos():
    rt, urg, b = R.choice(SCEN)
    loc_text, loc_gold, lm = place()
    pc, ptxt = R.choice(PEOPLE)
    msg = R.choice(b(ptxt, None, loc_text, lm))
    contact = phone() if R.random() < 0.65 else None
    if contact:
        msg += R.choice([f", call {contact}", f" contact {contact}", f". Ph: {contact}", f" whatsapp {contact}"])
    if R.random() < 0.2: msg = tamilize(msg, loc_text)
    msg = noisy(msg)
    return msg, {"location": loc_gold, "lat": None, "lon": None, "urgency": urg, "request_type": rt,
                 "people_count": pc, "contact": contact, "confidence": 0.85, "parseable": True, "notes": None}


def make_neg():
    msg = R.choice(NEG).format(a=R.choice(AREAS), y=R.choice(["2015", "2018", "2023"]))
    return noisy(msg), {"location": None, "lat": None, "lon": None, "urgency": "unknown", "request_type": "unknown",
                        "people_count": None, "contact": None, "confidence": 0.2, "parseable": False,
                        "notes": "Not a direct request for help."}


rows, seen = [], set()
while len(rows) < N:
    msg, lab = make_neg() if R.random() < 0.2 else make_pos()
    if msg in seen: continue
    seen.add(msg); rows.append({"id": f"s{len(rows):04d}", "text": msg, "target": lab})
out = Path(__file__).parent / "data" / "train_synth.jsonl"
out.parent.mkdir(exist_ok=True)
out.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
print(f"wrote {len(rows)} rows -> {out}")
