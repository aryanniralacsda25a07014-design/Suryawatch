"""Messages the server writes for people (verdicts, forecasts, plan notes) in English and Hindi.

    tr("hi", "dust.title")  ->  "पैनलों पर धूल – सफ़ाई करें"
Numbers are passed in already formatted; both languages use the same digits.
"""
from __future__ import annotations

TEXT = {
    "en": {
        # ---- daily verdict
        "no_data.title": "No reading yet",
        "no_data.msg": "Upload a photo of the inverter display to check today.",
        "too_early.title": "Too early to judge",
        "too_early.msg": "Check again after 10 AM.",
        "fault_state.title": "Inverter reports a fault",
        "fault_state.msg": "The inverter display showed \"{state}\" at {time}. Note the code, switch the inverter off and on "
                           "once if your installer allows it, and call your installer.",
        "smog.title": "Smog day - your panels are fine",
        "smog.msg": "Haze ({air}) cut about {haze}% of the sunlight today. Your panels made what the hazy sky allowed. "
                    "Nothing to fix.",
        "healthy.title": "Working well",
        "healthy.msg": "Your system made {pi}% of what today's sunlight should give. No action needed.",
        "fault.title": "Sudden drop - possible fault",
        "fault.msg": "Output fell to {pi}% of expected, far below your recent {median}%. Check the inverter for an error "
                     "code or a tripped switch, then call your installer.",
        "dust.title": "Dust on panels - clean them",
        "dust.msg": "Leaving the haze aside, your panels made {loss}% less than the sunlight allowed. That is about ₹{rupees} a week.",
        "dust.rain": " Rain is likely on {date} - wait for it and save the water.",
        "dust.clean": " Clean early morning or evening with plain water and a soft cloth.",
        "check.title": "Lower than expected",
        "check.msg": "Leaving the haze aside, output is {loss}% below what the sunlight allowed, even though the panels were "
                     "cleaned or rained on recently. Look for new shade, a loose cable or inverter warnings.",
        "area.title": "Low across your area - your panels are fine",
        "area.msg": "Most SuryaWatch rooftops within {km} km were low today too ({n} roofs, middle value {median}%), so the sky "
                    "cut the output, not dirt or a fault on your panels. Nothing to fix.",
        "cloudy": " It was a cloudy day, so this estimate is less certain.",
        "partial": " (Based on the {time} reading; the day is not over.)",
        # ---- next-days outlook
        "kwh": "about {kwh} kWh",
        "out.rain.title": "Rain likely: a free wash",
        "out.rain.msg": "About {mm} mm of rain is forecast. It will rinse the dust off, so skip cleaning before it. "
                        "Output will be low: {kwh}.",
        "out.smog.title": "Heavy smog expected",
        "out.smog.msg": "Haze may block about {haze}% of the sunlight ({air}). Expect {kwh} instead of {expected} kWh. "
                        "Low output will not mean your panels are dirty or faulty.",
        "out.air.pm": "PM2.5 around {pm}",
        "out.air.bad": "very poor air",
        "out.haze.title": "Hazy day expected",
        "out.haze.msg": "Haze may block about {haze}% of the sunlight. Expect {kwh}.",
        "out.cloudy.title": "Cloudy day expected",
        "out.cloudy.msg": "Clouds will cut output. Expect {kwh}.",
        "out.clear.title": "Clear, sunny day expected",
        "out.clear.msg": "Expect {kwh}. A good day to see your panels at their best: photograph the display at about "
                         "1 PM and 5:45 PM.",
        # ---- plan notes and assumptions
        "plan.load": "Your sanctioned load is {load} kW. Many DISCOMs limit rooftop solar to the sanctioned load, so you "
                     "may need to raise it to {kw} kW or choose a smaller system. Check with your DISCOM.",
        "plan.zero_bill": "Your bill is already ₹0 under the Delhi free-200-units scheme, so most of your return comes "
                          "from the generation incentive and surplus export credit.",
        "plan.roof": "Your roof, not your usage, limits the system size.",
        "as.roof": "{m2} m² of shade-free roof per kW; {pct}% of the roof usable",
        "as.pr": "Performance ratio {pr}, tilt gain {tilt}, {deg}% panel ageing per year",
        "as.cost": "Installed cost ₹{cost} per kW before subsidy (get vendor quotes)",
        "as.tariff": "DERC energy slabs only; PPAC, fixed charges and tax not included (real savings are usually higher)",
        "as.export": "Surplus units credited at ₹{rate} each",
    },
    "hi": {
        "no_data.title": "अभी कोई रीडिंग नहीं",
        "no_data.msg": "आज की जाँच के लिए इन्वर्टर डिस्प्ले की फ़ोटो अपलोड करें।",
        "too_early.title": "अभी कहना जल्दी है",
        "too_early.msg": "सुबह 10 बजे के बाद फिर देखें।",
        "fault_state.title": "इन्वर्टर में खराबी दिख रही है",
        "fault_state.msg": "इन्वर्टर डिस्प्ले पर {time} बजे \"{state}\" दिखा। यह कोड नोट कर लें, अगर इंस्टॉलर अनुमति दे तो "
                           "इन्वर्टर को एक बार बंद करके फिर चालू करें, और अपने इंस्टॉलर को फ़ोन करें।",
        "smog.title": "स्मॉग वाला दिन – आपके पैनल ठीक हैं",
        "smog.msg": "धुंध ({air}) ने आज लगभग {haze}% धूप रोक दी। धुंधले आसमान में जितनी बिजली बन सकती थी, आपके पैनलों ने "
                    "उतनी बनाई। कुछ ठीक करने की ज़रूरत नहीं।",
        "healthy.title": "ठीक काम कर रहा है",
        "healthy.msg": "आज की धूप से जितनी बिजली बननी चाहिए थी, आपके सिस्टम ने उसका {pi}% बनाया। कुछ करने की ज़रूरत नहीं।",
        "fault.title": "अचानक गिरावट – शायद कोई खराबी",
        "fault.msg": "उत्पादन अनुमान का सिर्फ़ {pi}% रह गया, जो आपके हाल के {median}% से बहुत कम है। इन्वर्टर पर कोई एरर कोड "
                     "या गिरा हुआ स्विच देखें, फिर अपने इंस्टॉलर को फ़ोन करें।",
        "dust.title": "पैनलों पर धूल – सफ़ाई करें",
        "dust.msg": "धुंध का असर अलग रखें तो भी आपके पैनलों ने धूप से संभव बिजली से {loss}% कम बनाई। यह हर हफ़्ते लगभग ₹{rupees} का नुकसान है।",
        "dust.rain": " {date} को बारिश की संभावना है – उसका इंतज़ार करें और पानी बचाएँ।",
        "dust.clean": " सुबह जल्दी या शाम को सादे पानी और मुलायम कपड़े से साफ़ करें।",
        "check.title": "उम्मीद से कम",
        "check.msg": "हाल ही में पैनल साफ़ हुए या बारिश हुई, फिर भी धुंध का असर अलग रखकर उत्पादन धूप से संभव से {loss}% कम है। "
                     "कोई नई छाया, ढीला तार या इन्वर्टर की चेतावनी देखें।",
        "area.title": "पूरे इलाके में कम – आपके पैनल ठीक हैं",
        "area.msg": "{km} किमी के अंदर ज़्यादातर SuryaWatch छतों पर भी आज उत्पादन कम रहा ({n} छतें, बीच का मान {median}%), "
                    "इसलिए कमी आसमान की वजह से है, आपके पैनलों की धूल या खराबी से नहीं। कुछ ठीक करने की ज़रूरत नहीं।",
        "cloudy": " आज बादल थे, इसलिए यह अनुमान थोड़ा कम पक्का है।",
        "partial": " ({time} की रीडिंग के आधार पर; दिन अभी बाकी है।)",
        "kwh": "लगभग {kwh} kWh",
        "out.rain.title": "बारिश की संभावना: मुफ़्त धुलाई",
        "out.rain.msg": "लगभग {mm} मिमी बारिश का अनुमान है। इससे धूल धुल जाएगी, इसलिए उससे पहले सफ़ाई न करें। उत्पादन कम "
                        "रहेगा: {kwh}।",
        "out.smog.title": "भारी स्मॉग की आशंका",
        "out.smog.msg": "धुंध लगभग {haze}% धूप रोक सकती है ({air})। {expected} kWh की जगह {kwh} की उम्मीद रखें। कम उत्पादन "
                        "का मतलब यह नहीं होगा कि आपके पैनल गंदे या खराब हैं।",
        "out.air.pm": "PM2.5 लगभग {pm}",
        "out.air.bad": "हवा बहुत खराब",
        "out.haze.title": "धुंधला दिन रहने की संभावना",
        "out.haze.msg": "धुंध लगभग {haze}% धूप रोक सकती है। {kwh} की उम्मीद रखें।",
        "out.cloudy.title": "बादल रहने की संभावना",
        "out.cloudy.msg": "बादलों से उत्पादन घटेगा। {kwh} की उम्मीद रखें।",
        "out.clear.title": "साफ़, धूप वाला दिन रहने की संभावना",
        "out.clear.msg": "{kwh} की उम्मीद रखें। पैनलों का सबसे अच्छा प्रदर्शन देखने का अच्छा दिन: लगभग दोपहर 1 बजे और "
                         "शाम 5:45 बजे डिस्प्ले की फ़ोटो लें।",
        "plan.load": "आपका स्वीकृत लोड {load} kW है। कई बिजली कंपनियाँ रूफ़टॉप सोलर को स्वीकृत लोड तक सीमित रखती हैं, इसलिए "
                     "आपको लोड बढ़ाकर {kw} kW करना पड़ सकता है या छोटा सिस्टम चुनना पड़ सकता है। अपनी बिजली कंपनी से पूछ लें।",
        "plan.zero_bill": "दिल्ली की 200 यूनिट मुफ़्त योजना से आपका बिल पहले ही ₹0 है, इसलिए आपका ज़्यादातर फ़ायदा उत्पादन "
                          "प्रोत्साहन और ग्रिड को दी गई अतिरिक्त बिजली के क्रेडिट से आएगा।",
        "plan.roof": "सिस्टम का आकार आपकी खपत से नहीं, आपकी छत की जगह से तय हुआ है।",
        "as.roof": "हर kW के लिए {m2} वर्ग मीटर छाया-रहित छत; छत का {pct}% हिस्सा इस्तेमाल लायक",
        "as.pr": "परफ़ॉर्मेंस रेशियो {pr}, झुकाव से फ़ायदा {tilt}, हर साल पैनलों में {deg}% गिरावट",
        "as.cost": "सब्सिडी से पहले लगाने की लागत ₹{cost} प्रति kW (वेंडरों से कोटेशन लें)",
        "as.tariff": "सिर्फ़ DERC के ऊर्जा स्लैब; PPAC, फ़िक्स्ड चार्ज और टैक्स शामिल नहीं (असल बचत आमतौर पर ज़्यादा होती है)",
        "as.export": "अतिरिक्त यूनिट ₹{rate} प्रति यूनिट के हिसाब से क्रेडिट",
    },
}


def lang_of(value) -> str:
    return "hi" if str(value or "").lower().startswith("hi") else "en"


def tr(lang: str, key: str, **values) -> str:
    table = TEXT.get(lang_of(lang), TEXT["en"])
    template = table.get(key) or TEXT["en"][key]
    return template.format(**values) if values else template
