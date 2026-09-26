#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Seva Mitra - Citizen Services Agent (Prototype v1.0)
====================================================

A WhatsApp-style citizen services assistant for Andhra Pradesh & Telangana
covering pensions, certificates and basic tax questions, in Telugu (script),
romanised Telugu (Tenglish) and English.

Implements the design in "Citizen Services Agent - Build Blueprint v1.0":
  - language/script matching, one-question-at-a-time application assistance,
  - eligibility checks, document collection with a case reference number,
  - status tracking, escalation, OTP-safety and distress guardrails.

Three run modes (no API keys or installs needed - pure Python 3 stdlib):

  python3 seva_mitra_prototype.py chat     # interactive chat in your terminal
  python3 seva_mitra_prototype.py demo     # scripted demo: 3 citizens, 3 languages
  python3 seva_mitra_prototype.py serve    # WhatsApp-style webhook server on :8787
                                            #   POST /webhook  {"from":"+91...", "text":"hi"}
                                            #   -> {"replies": ["..."]}

To connect the real channel later (Gupshup / Twilio / Meta Cloud API sandbox),
point the provider's webhook URL at this server's /webhook endpoint; the JSON
shape is already WhatsApp-Cloud-API-like and easy to adapt.

This is a prototype: facts are embedded from the blueprint's v1 knowledge
base (verified September 2026) and MUST be re-verified against official
portals before any real deployment. The bot informs; the government decides.
"""

import json
import os
import re
import sys
import time
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CASES_FILE = os.path.join(os.getcwd(), "cases.json")

# ---------------------------------------------------------------------------
# Message catalog: en = English, te = Telugu script, roman = romanised Telugu
# Placeholders like {reason} are filled at runtime via string replace.
# ---------------------------------------------------------------------------
CATALOG = {
    "en": {
        "greet": "Namaskaram! I am Seva Mitra, your citizen services helper.\nReply 1 for English, 2 for Telugu (Telugu kosam 2).",
        "choose_state": "Which state do you live in? Reply 1 for Andhra Pradesh, 2 for Telangana.",
        "main_menu": "How can I help you today? Reply 1 for Pensions, 2 for Certificates, 3 for Taxes, 4 to Track my application, 5 to Talk to a person.",
        "pension_menu": "Which pension do you need? Reply 1 for Old age pension, 2 for Widow pension, 3 for Disability pension, 4 for Chronic disease pension.",
        "certs_menu": "Which certificate do you need? Reply 1 for Income certificate, 2 for Caste certificate, 3 for Birth certificate, 4 for Residence certificate.",
        "tax_menu": "For tax questions, reply 1 for Income tax, 2 for GST.",
        "ask_name": "What is your name?",
        "ask_age": "What is your age? Please type the number.",
        "ask_district": "Which district do you live in?",
        "ask_ration": "Do you have a ration card? Reply 1 for white ration card, 2 for any other card, 3 for no card.",
        "ask_bank": "Do you have a bank account or post office account in your own name? Reply 1 for yes, 2 for no.",
        "ask_death_cert": "Do you have your husband's death certificate? Reply 1 for yes, 2 for no.",
        "ask_sadarem": "Do you have a SADAREM certificate showing 40 percent or more disability? Reply 1 for yes, 2 for no.",
        "ask_medical": "Do you have medical documents for your condition, like dialysis or thalassemia records? Reply 1 for yes, 2 for no.",
        "menu_hint": "Reply MENU at any time to return to the main menu.",
        "eligible": "Good news! Based on your answers, you are likely eligible. Please verify once at your nearest office or on the official portal before applying.",
        "not_eligible": "Sorry, you may not be eligible for this pension. Reason: {reason}\nYou can still visit your nearest office and ask them to confirm, because rules have exceptions.",
        "reason_age": "your age is below the limit for this pension.",
        "reason_ration": "a white ration card or BPL card is usually required for this pension.",
        "reason_doc": "this document is required to apply for this pension.",
        "reason_bank": "a bank account in your own name is needed to receive the pension.",
        "checklist": "Please keep these documents ready:\n{docs}\nSend a photo of each document here. Type DONE when you have sent all of them.",
        "doc_ok": "Received and clear: {doc}\nNext: {next}",
        "doc_problem": "The photo of {doc} is not clear or is incomplete. Please send it again in daylight with all four corners of the document visible.",
        "doc_all_done": "All documents received.",
        "summary": "Thank you, {name}!\nHere is your summary.\nScheme: {scheme}\nDistrict: {district}\nDocuments verified: {docs}\nNext steps: visit {office} with your original documents, or apply on the portal {portal}.\nYour reference number is {ref}. We will message you when there is an update.",
        "track_intro": "Please type your reference number, for example SM-1234.",
        "track_not_found": "I could not find this reference number. Please check and type it again, or reply MENU to start over.",
        "track_status": "Your application {ref} status: {status}\nReply MENU for the main menu.",
        "st_received": "Received at Seva Mitra.",
        "st_verify": "Under verification at the office.",
        "st_recommended": "Recommended to the sanctioning officer.",
        "st_approved": "Approved. Please download your certificate or check your bank account.",
        "escalate": "I am connecting you to a human agent. They will reply between 10 AM and 6 PM. Meanwhile I have noted your case and they will see the full history.",
        "out_of_scope": "Sorry, I can only help with government schemes, certificates and tax questions for Andhra Pradesh and Telangana. Reply MENU to see what I can do.",
        "otp_warning": "Important: I will never ask for your OTP, PIN or password. No real government official will either. Please never share them with anyone.",
        "distress": "I hear you, and I am sorry you are going through a hard time. Help is available right now. The Tele-MANAS helpline 14416 is free, open 24 hours, and speaks Telugu. I am also alerting our team to check on you.",
        "cert_income": "Income certificate: issued by the Tahsildar. Documents needed: application form, income proof such as pay slip, IT return or self-declaration, ration card or Aadhaar, and one photo. Fee: about Rs. 35. Apply at a MeeSeva centre or on the AP Seva portal. Official timeline: 7 working days.",
        "cert_caste": "Caste certificate, also called integrated certificate with nativity and date of birth: documents needed: SSC memo or transfer certificate, caste certificate of a family member if available, study certificates, ration card or Aadhaar. Apply at MeeSeva or on the AP Seva portal. Timeline: about 30 days.",
        "cert_birth": "Birth certificate: every birth should be registered within 21 days at the municipality or MRO office. Documents: hospital record and parents' Aadhaar. If the birth was not registered and is more than one year old, it becomes a late registration through the RDO and takes about 60 days.",
        "cert_residence": "Residence certificate: issued by the Tahsildar or MRO. Documents: application, ration card or Aadhaar, and address proof such as an electricity bill. Apply at MeeSeva. Timeline: 7 to 30 days.",
        "tax_it": "Income tax basics for the current year, new regime: no tax up to Rs. 4 lakh income. 5% up to 8 lakh, 10% up to 12 lakh, 15% up to 16 lakh, 20% up to 20 lakh, 25% up to 24 lakh, 30% above that. With the rebate, salaried persons pay zero tax up to Rs. 12.75 lakh. File your return on incometax.gov.in. For advice for your specific case, please consult a qualified chartered accountant.",
        "tax_gst": "GST basics: registration becomes necessary when yearly turnover crosses Rs. 40 lakh for goods, or Rs. 20 lakh for services, in most states. In Telangana the limits are lower: Rs. 20 lakh for goods and Rs. 10 lakh for services. Since September 2025 the main rates are 5% and 18%, with 40% for luxury goods. For your specific business, please consult a chartered accountant.",
        # labels for the scheme info card
        "lbl_scheme": "Scheme",
        "lbl_amount": "Monthly amount",
        "lbl_office": "Where to apply",
        "lbl_portal": "Portal",
    },
    "te": {
        "greet": "నమస్కారం! నేను సేవా మిత్ర, మీ పౌర సేవల సహాయకుడిని.\nReply 1 for English, తెలుగు కోసం 2 అని రిప్లై ఇవ్వండి.",
        "choose_state": "మీరు ఏ రాష్ట్రంలో నివసిస్తున్నారు? ఆంధ్రప్రదేశ్ కోసం 1, తెలంగాణ కోసం 2 అని రిప్లై ఇవ్వండి.",
        "main_menu": "ఈరోజు నేను మీకు ఎలా సహాయపడగలను? పెన్షన్ల కోసం 1, సర్టిఫికెట్ల కోసం 2, పన్నుల కోసం 3, నా అప్లికేషన్‌ను ట్రాక్ చేయడానికి 4, ఒక వ్యక్తితో మాట్లాడటానికి 5 అని రిప్లై ఇవ్వండి.",
        "pension_menu": "మీకు ఏ పెన్షన్ కావాలి? వృద్ధాప్య పెన్షన్ కోసం 1, వితంతు పెన్షన్ కోసం 2, వికలాంగుల పెన్షన్ కోసం 3, దీర్ఘకాలిక వ్యాధి పెన్షన్ కోసం 4 అని రిప్లై ఇవ్వండి.",
        "certs_menu": "మీకు ఏ సర్టిఫికెట్ కావాలి? ఆదాయ ధృవీకరణ పత్రం కోసం 1, కుల ధృవీకరణ పత్రం కోసం 2, జనన ధృవీకరణ పత్రం కోసం 3, నివాస ధృవీకరణ పత్రం కోసం 4 అని రిప్లై ఇవ్వండి.",
        "tax_menu": "పన్ను ప్రశ్నల కోసం, ఆదాయపు పన్ను కోసం 1, GST కోసం 2 అని రిప్లై ఇవ్వండి.",
        "ask_name": "మీ పేరు ఏమిటి?",
        "ask_age": "మీ వయస్సు ఎంత? దయచేసి నంబర్‌ను టైప్ చేయండి.",
        "ask_district": "మీరు ఏ జిల్లాలో నివసిస్తున్నారు?",
        "ask_ration": "మీకు రేషన్ కార్డు ఉందా? తెల్ల రేషన్ కార్డు కోసం 1, వేరే ఏదైనా కార్డు కోసం 2, కార్డు లేదు కోసం 3 అని రిప్లై ఇవ్వండి.",
        "ask_bank": "మీ పేరు మీద బ్యాంక్ ఖాతా లేదా పోస్ట్ ఆఫీస్ ఖాతా ఉందా? అవును కోసం 1, లేదు కోసం 2 అని రిప్లై ఇవ్వండి.",
        "ask_death_cert": "మీ భర్త మరణ ధృవీకరణ పత్రం మీ వద్ద ఉందా? అవును కోసం 1, లేదు కోసం 2 అని రిప్లై ఇవ్వండి.",
        "ask_sadarem": "40 శాతం లేదా అంతకంటే ఎక్కువ వైకల్యం ఉన్న SADAREM సర్టిఫికెట్ మీ వద్ద ఉందా? అవును కోసం 1, లేదు కోసం 2 అని రిప్లై ఇవ్వండి.",
        "ask_medical": "డయాలసిస్ లేదా తలసేమియా రికార్డుల వంటి మీ పరిస్థితికి సంబంధించిన వైద్య పత్రాలు మీ వద్ద ఉన్నాయా? అవును కోసం 1, లేదు కోసం 2 అని రిప్లై ఇవ్వండి.",
        "menu_hint": "మెయిన్ మెనూకి వెళ్లడానికి ఏ సమయంలోనైనా MENU అని రిప్లై ఇవ్వండి.",
        "eligible": "శుభవార్త! మీ సమాధానాల ఆధారంగా, మీరు అర్హులు అయ్యే అవకాశం ఉంది. దయచేసి దరఖాస్తు చేసుకునే ముందు మీ దగ్గరి కార్యాలయంలో లేదా అధికారిక పోర్టల్‌లో ఒకసారి ధృవీకరించుకోండి.",
        "not_eligible": "క్షమించండి, మీరు ఈ పెన్షన్‌కు అర్హులు కాకపోవచ్చు. కారణం: {reason}\nమీరు ఇంకా మీ దగ్గరి కార్యాలయాన్ని సందర్శించి నిర్ధారించమని అడగవచ్చు, ఎందుకంటే నిబంధనలకు మినహాయింపులు ఉంటాయి.",
        "reason_age": "ఈ పెన్షన్ కోసం మీ వయస్సు పరిమితి కంటే తక్కువగా ఉంది.",
        "reason_ration": "ఈ పెన్షన్ కోసం సాధారణంగా తెల్ల రేషన్ కార్డు లేదా BPL కార్డు అవసరం.",
        "reason_doc": "ఈ పెన్షన్ కోసం దరఖాస్తు చేయడానికి ఈ పత్రం అవసరం.",
        "reason_bank": "పెన్షన్ అందుకోవడానికి మీ పేరు మీద బ్యాంక్ ఖాతా అవసరం.",
        "checklist": "దయచేసి ఈ పత్రాలను సిద్ధంగా ఉంచండి:\n{docs}\nప్రతి పత్రం ఫోటోను ఇక్కడ పంపండి. వాటన్నింటినీ పంపిన తర్వాత DONE అని టైప్ చేయండి.",
        "doc_ok": "అందింది మరియు స్పష్టంగా ఉంది: {doc}\nతదుపరి: {next}",
        "doc_problem": "{doc} ఫోటో స్పష్టంగా లేదు లేదా అసంపూర్ణంగా ఉంది. దయచేసి పత్రం యొక్క నాలుగు మూలలు కనిపించేలా పగటిపూట మళ్లీ పంపండి.",
        "doc_all_done": "అన్ని పత్రాలు అందాయి.",
        "summary": "ధన్యవాదాలు, {name}!\nఇది మీ సారాంశం.\nపథకం: {scheme}\nజిల్లా: {district}\nధృవీకరించబడిన పత్రాలు: {docs}\nతదుపరి దశలు: మీ అసలు పత్రాలతో {office} ని సందర్శించండి లేదా {portal} లో దరఖాస్తు చేసుకోండి.\nమీ రిఫరెన్స్ నంబర్ {ref}. అప్‌డేట్ ఉన్నప్పుడు మేము మీకు మెసేజ్ చేస్తాము.",
        "track_intro": "దయచేసి మీ రిఫరెన్స్ నంబర్‌ను టైప్ చేయండి, ఉదాహరణకు SM-1234.",
        "track_not_found": "ఈ రిఫరెన్స్ నంబర్ నాకు దొరకలేదు. దయచేసి చెక్ చేసి మళ్లీ టైప్ చేయండి లేదా మళ్లీ ప్రారంభించడానికి MENU అని రిప్లై ఇవ్వండి.",
        "track_status": "మీ అప్లికేషన్ {ref} స్థితి: {status}\nమెయిన్ మెనూ కోసం MENU అని రిప్లై ఇవ్వండి.",
        "st_received": "Seva Mitra వద్ద అందింది.",
        "st_verify": "ఆఫీసులో ధృవీకరణలో ఉంది.",
        "st_recommended": "మంజూరు చేసే అధికారికి సిఫార్సు చేయబడింది.",
        "st_approved": "ఆమోదించబడింది. దయచేసి మీ సర్టిఫికెట్‌ను డౌన్‌లోడ్ చేసుకోండి లేదా మీ బ్యాంక్ ఖాతాను చెక్ చేసుకోండి.",
        "escalate": "నేను మిమ్మల్ని ఒక హ్యూమన్ ఏజెంట్‌కు కనెక్ట్ చేస్తున్నాను. వారు ఉదయం 10 గంటల నుండి సాయంత్రం 6 గంటల మధ్య రిప్లై ఇస్తారు. ఈలోగా నేను మీ కేసును నోట్ చేశాను మరియు వారు పూర్తి చరిత్రను చూస్తారు.",
        "out_of_scope": "క్షమించండి, నేను ఆంధ్రప్రదేశ్ మరియు తెలంగాణ కోసం ప్రభుత్వ పథకాలు, సర్టిఫికెట్లు మరియు పన్ను ప్రశ్నలకు మాత్రమే సహాయం చేయగలను. నేను ఏమి చేయగలనో చూడటానికి MENU అని రిప్లై ఇవ్వండి.",
        "otp_warning": "ముఖ్య గమనిక: నేను ఎప్పుడూ మీ OTP, PIN లేదా పాస్‌వర్డ్ అడగను. ఏ నిజమైన ప్రభుత్వ అధికారి కూడా అడగరు. దయచేసి వాటిని ఎవరితోనూ పంచుకోవద్దు.",
        "distress": "మీ మాట విన్నాను, మరియు మీరు కష్టకాలంలో ఉన్నందుకు నన్ను క్షమించండి. సహాయం ఇప్పుడే అందుబాటులో ఉంది. Tele-MANAS హెల్ప్‌లైన్ 14416 ఉచితం, 24 గంటలు తెరిచి ఉంటుంది మరియు తెలుగు మాట్లాడుతుంది. మిమ్మల్ని చెక్ చేయమని నేను మా బృందాన్ని కూడా అప్రమత్తం చేస్తున్నాను.",
        "cert_income": "ఆదాయ ధృవీకరణ పత్రం: తహసీల్దార్ జారీ చేస్తారు. అవసరమైన పత్రాలు: అప్లికేషన్ ఫారమ్, పే స్లిప్, IT రిటర్న్ లేదా స్వీయ-ప్రకటన వంటి ఆదాయ రుజువు, రేషన్ కార్డు లేదా ఆధార్ మరియు ఒక ఫోటో. ఫీజు: సుమారు 35 రూపాయలు. MeeSeva కేంద్రం లేదా AP Seva పోర్టల్‌లో దరఖాస్తు చేసుకోండి. అధికారిక సమయం: 7 పని దినాలు.",
        "cert_caste": "కుల ధృవీకరణ పత్రం, దీనిని ఇంటిగ్రేటెడ్ సర్టిఫికెట్ విత్ నేటివిటీ మరియు డేట్ ఆఫ్ బర్త్ అని కూడా అంటారు: అవసరమైన పత్రాలు: SSC మెమో లేదా ట్రాన్స్‌ఫర్ సర్టిఫికేట్, అందుబాటులో ఉంటే కుటుంబ సభ్యుని కుల ధృవీకరణ పత్రం, స్టడీ సర్టిఫికేట్లు, రేషన్ కార్డు లేదా ఆధార్. MeeSeva లేదా AP Seva పోర్టల్‌లో దరఖాస్తు చేసుకోండి. సమయం: సుమారు 30 రోజులు.",
        "cert_birth": "జనన ధృవీకరణ పత్రం: ప్రతి జననం 21 రోజుల్లోపు మున్సిపాలిటీ లేదా MRO ఆఫీసులో నమోదు చేయబడాలి. పత్రాలు: ఆసుపత్రి రికార్డు మరియు తల్లిదండ్రుల ఆధార్. జననం నమోదు చేయబడకపోతే మరియు ఒక సంవత్సరం కంటే పాతది అయితే, ఇది RDO ద్వారా లేట్ రిజిస్ట్రేషన్ అవుతుంది మరియు సుమారు 60 రోజులు పడుతుంది.",
        "cert_residence": "నివాస ధృవీకరణ పత్రం: తహసీల్దార్ లేదా MRO జారీ చేస్తారు. పత్రాలు: అప్లికేషన్, రేషన్ కార్డు లేదా ఆధార్ మరియు విద్యుత్ బిల్లు వంటి చిరునామా రుజువు. MeeSeva లో దరఖాస్తు చేసుకోండి. సమయం: 7 నుండి 30 రోజులు.",
        "tax_it": "ప్రస్తుత సంవత్సరానికి ఆదాయపు పన్ను ప్రాథమిక అంశాలు, కొత్త విధానం: 4 లక్షల రూపాయల ఆదాయం వరకు పన్ను లేదు. 8 లక్షల వరకు 5 శాతం, 12 లక్షల వరకు 10 శాతం, 16 లక్షల వరకు 15 శాతం, 20 లక్షల వరకు 20 శాతం, 24 లక్షల వరకు 25 శాతం మరియు దాని పైన 30 శాతం. రాయితీతో, జీతం తీసుకునే వ్యక్తులు 12.75 లక్షల రూపాయల వరకు సున్నా పన్ను చెల్లిస్తారు. incometax.gov.in లో మీ రిటర్న్‌ను ఫైల్ చేయండి. మీ నిర్దిష్ట కేసుకు సలహా కోసం, దయచేసి అర్హత కలిగిన చార్టర్డ్ అకౌంటెంట్‌ను సంప్రదించండి.",
        "tax_gst": "GST ప్రాథమిక అంశాలు: చాలా రాష్ట్రాల్లో వస్తువులకు వార్షిక టర్నోవర్ 40 లక్షల రూపాయలు లేదా సేవలకు 20 లక్షల రూపాయలు దాటినప్పుడు రిజిస్ట్రేషన్ అవసరం అవుతుంది. తెలంగాణలో పరిమితులు తక్కువగా ఉన్నాయి: వస్తువులకు 20 లక్షలు మరియు సేవలకు 10 లక్షలు. సెప్టెంబర్ 2025 నుండి ప్రధాన రేట్లు 5 శాతం మరియు 18 శాతం, లగ్జరీ వస్తువులకు 40 శాతం. మీ నిర్దిష్ట వ్యాపారం కోసం, దయచేసి చార్టర్డ్ అకౌంటెంట్‌ను సంప్రదించండి.",
        "lbl_scheme": "పథకం",
        "lbl_amount": "నెలవారీ మొత్తం",
        "lbl_office": "ఎక్కడ దరఖాస్తు చేయాలి",
        "lbl_portal": "పోర్టల్",
    },
    "roman": {
        "greet": "Namaskaram! Nenu Seva Mitra, mee praapara sevala sahayakudu.\nReply 1 for English, Telugu kosam 2 ani reply ivvandi.",
        "choose_state": "Meelu ye state lo untunnaru? Andhra Pradesh kosam 1, Telangana kosam 2 ani reply ivvandi.",
        "main_menu": "E roju nenu meeku ela help cheyagalanu? Pensions kosam 1, certificates kosam 2, taxes kosam 3, na application track cheyadaniki 4, oka vyakti tho matladadaniki 5 ani reply ivvandi.",
        "pension_menu": "Meeku ye pension kavali? Old age pension kosam 1, widow pension kosam 2, disability pension kosam 3, chronic disease pension kosam 4 ani reply ivvandi.",
        "certs_menu": "Meeku ye certificate kavali? Income certificate kosam 1, caste certificate kosam 2, birth certificate kosam 3, residence certificate kosam 4 ani reply ivvandi.",
        "tax_menu": "Tax questions kosam, income tax kosam 1, GST kosam 2 ani reply ivvandi.",
        "ask_name": "Mee peru emi?",
        "ask_age": "Mee vayasu entha? Dayachesi number type cheyandi.",
        "ask_district": "Meelu ye district lo untunnaru?",
        "ask_ration": "Meeku ration card unda? White ration card kosam 1, vere yeina card kosam 2, card ledu kosam 3 ani reply ivvandi.",
        "ask_bank": "Mee peru meeda bank account leda post office account unda? Avunu kosam 1, ledu kosam 2 ani reply ivvandi.",
        "ask_death_cert": "Mee bharta marana certificate meeda unda? Avunu kosam 1, ledu kosam 2 ani reply ivvandi.",
        "ask_sadarem": "40 percent leda antakante ekkuva disability unna SADAREM certificate meeda unda? Avunu kosam 1, ledu kosam 2 ani reply ivvandi.",
        "ask_medical": "Dialysis leda thalassemia records lanti mee paristhithiki sambandhinchina vaidya patralu meeda unnaya? Avunu kosam 1, ledu kosam 2 ani reply ivvandi.",
        "menu_hint": "Main menu ki velladaniki ye samayam lo MENU ani reply ivvandi.",
        "eligible": "Shubha varta! Mee samadhanaala adharam meelu arhudu ayye avakasam undi. Dayachesi apply chese mundu meea daggari office lo leda official portal lo oasari verify chesukondi.",
        "not_eligible": "Kshaminchandi, meelu ee pension ki arhudu kavakapovachchu. Karanam: {reason}\nMeelu inka meea daggari office ni visit chesi confirm cheyamani adagavachchu, endukante rules ki exceptions untayi.",
        "reason_age": "ee pension kosam mee vayasu limit kante takkuva ga undi.",
        "reason_ration": "ee pension kosam samanyanga white ration card leda BPL card avasaram.",
        "reason_doc": "ee pension ki apply cheyadaniki ee patram avasaram.",
        "reason_bank": "pension andukovadaniki mee peru meeda bank account avasaram.",
        "checklist": "Dayachesi ee patralanu sidham ga unchandi:\n{docs}\nPrathi patram photo ikkada pampandi. Vatanni anni pampina tarvata DONE ani type cheyandi.",
        "doc_ok": "Dabbayindi mariyu spashtam ga undi: {doc}\nThadupari: {next}",
        "doc_problem": "{doc} photo spashtam ga ledu leda asampoornam ga undi. Dayachesi patram ye nau moogalu kanipinche la padi pampandi.",
        "doc_all_done": "Anni patralu dabbayayi.",
        "summary": "Dhanyavadalu, {name}!\nIdi mee summary.\nPathakam: {scheme}\nDistrict: {district}\nVerify ayyina patralu: {docs}\nThadupari steps: mee asalu patralatho {office} ni visit cheyandi leda {portal} lo apply cheyandi.\nMee reference number {ref}. Update unnapudu memu meeku message chestamu.",
        "track_intro": "Dayachesi mee reference number type cheyandi, udaharanaku SM-1234.",
        "track_not_found": "Ee reference number naaku dorakaledu. Dayachesi check chesi malli type cheyandi leda malli start cheyadaniki MENU ani reply ivvandi.",
        "track_status": "Mee application {ref} sthithi: {status}\nMain menu kosam MENU ani reply ivvandi.",
        "st_received": "Seva Mitra lo dabbayindi.",
        "st_verify": "Office lo verification lo undi.",
        "st_recommended": "Manjoor chese adhikariki sipharasu cheyabaddadi.",
        "st_approved": "Amodinchabaddadi. Dayachesi mee certificate download chesukondi leda mee bank account check chesukondi.",
        "escalate": "Nenu mimmalni oka human agent ki connect chestunnanu. Varu uyalo 10 gantal nunchi sayantram 6 gantala madhya reply istaru. Eeloga nenu mee case ni note chesanu mariyu varu poorthi chitram chustaru.",
        "out_of_scope": "Kshaminchandi, nenu Andhra Pradesh mariyu Telangana kosam prabhutva pathakalu, certificates mariyu tax questions ke matrame help cheyagalanu. Nenu emi cheyagalano chudataniki MENU ani reply ivvandi.",
        "otp_warning": "Mookhya gamanika: nenu yeppudu mee OTP, PIN leda password adaganu. Ye nijamaina prabhutva adhikari kuda adagadu. Dayachesi vatini evaritho pan chesukoddaku.",
        "distress": "Mee mata vinnanu, mariyu meelu kashta samayam lo unnanduku nannu kshaminchandi. Sahayam ippude untundi. Tele-MANAS helpline 14416 free, 24 gantalu terichi untundi mariyu Telugu matladutundi. Mimmalni check cheyamani nenu maa team ni kuda alert chestunnanu.",
        "cert_income": "Income certificate: Tahsildar issue chestadu. Avasaramaina patralu: application form, pay slip, IT return leda self-declaration lanti aayada rujuvu, ration card leda Aadhaar, mariyu oka photo. Fee: sunakshma 35 rupayalu. MeeSeva centre leda AP Seva portal lo apply cheyandi. Official time: 7 pani dinamulu.",
        "cert_caste": "Caste certificate, deeni ni integrated certificate with nativity and date of birth ani kuda antaru: avasaramaina patralu: SSC memo leda transfer certificate, unte kutumba sadharudu/sadharichi caste certificate, study certificates, ration card leda Aadhaar. MeeSeva leda AP Seva portal lo apply cheyandi. Time: sunakshma 30 rojulu.",
        "cert_birth": "Birth certificate: prati janmamu 21 rojulalo municipality leda MRO office lo register avvalsindi. Patralu: hospital record mariyu talli tandrula Aadhaar. Janmamu register avvakapote mariyu oka samvatsaram kanta padaite, adi RDO dwara late registration avutundi mariyu sunakshma 60 rojulu padutundi.",
        "cert_residence": "Residence certificate: Tahsildar leda MRO issue chestadu. Patralu: application, ration card leda Aadhaar, mariyu current bill lanti address proof. MeeSeva lo apply cheyandi. Time: 7 nunchi 30 rojulu.",
        "tax_it": "Prasthuta samvatsaraku income tax basics, kotha vidhanam: 4 lakhalu aayada varaku tax ledu. 8 lakhalaku 5 shatam, 12 lakhalaku 10 shatam, 16 lakhalaku 15 shatam, 20 lakhalaku 20 shatam, 24 lakhalaku 25 shatam, mariyu daapina 30 shatam. Rebate tho, salaried vyaktulu 12.75 lakhalu rupayalu varaku zero tax chellistaru. incometax.gov.in lo mee return file cheyandi. Mee specific case ku salah kosam, dayachesi qualified CA ni sampreshinchandi.",
        "tax_gst": "GST basics: chala states lo vastuvulaku yearly turnover 40 lakhalu leda services ku 20 lakhalu daagite registration avasaram avutundi. Telanganana limits takkuva ga unnayi: vastuvulaku 20 lakhalu mariyu services ku 10 lakhalu. September 2025 nunchi pradhana rates 5 shatam mariyu 18 shatam, luxury vastuvulaku 40 shatam. Mee specific vyaparam kosam, dayachesi CA ni sampreshinchandi.",
        "lbl_scheme": "Pathakam",
        "lbl_amount": "Nelavari motham",
        "lbl_office": "Yekkada apply cheyali",
        "lbl_portal": "Portal",
    },
}

# ---------------------------------------------------------------------------
# Scheme knowledge base (v1 - verify against official portals before real use)
# ---------------------------------------------------------------------------
SCHEMES = {
    ("AP", "old_age"): dict(
        name="Old Age Pension (NTR Bharosa - AP)", amount="Rs. 4,000 / month",
        min_age=60, office="Grama / Ward Sachivalayam", portal="sspensions.ap.gov.in",
        extra_doc=None),
    ("TS", "old_age"): dict(
        name="Old Age Pension (Cheyutha - Telangana)", amount="Rs. 4,000 / month",
        min_age=57, office="Mee-Seva centre / Gram Panchayat", portal="cheyutha.telangana.gov.in",
        extra_doc=None),
    ("AP", "widow"): dict(
        name="Widow Pension (NTR Bharosa - AP)", amount="Rs. 4,000 / month",
        min_age=18, office="Grama / Ward Sachivalayam", portal="sspensions.ap.gov.in",
        extra_doc="death"),
    ("TS", "widow"): dict(
        name="Widow Pension (Cheyutha - Telangana)", amount="Rs. 4,000 / month",
        min_age=18, office="Mee-Seva centre / Gram Panchayat", portal="cheyutha.telangana.gov.in",
        extra_doc="death"),
    ("AP", "disabled"): dict(
        name="Disability Pension (NTR Bharosa - AP)", amount="Rs. 6,000 / month",
        min_age=None, office="Grama / Ward Sachivalayam", portal="sspensions.ap.gov.in",
        extra_doc="sadarem"),
    ("TS", "disabled"): dict(
        name="Disability Pension (Cheyutha - Telangana)", amount="Rs. 6,000 / month",
        min_age=None, office="Mee-Seva centre / Gram Panchayat", portal="cheyutha.telangana.gov.in",
        extra_doc="sadarem"),
    ("AP", "chronic"): dict(
        name="Chronic Disease Pension (NTR Bharosa - AP)", amount="Rs. 10,000 / month",
        min_age=None, office="Grama / Ward Sachivalayam", portal="sspensions.ap.gov.in",
        extra_doc="medical"),
    ("TS", "chronic"): dict(
        name="Chronic Disease Pension (Cheyutha - Telangana)", amount="Rs. 4,000 / month",
        min_age=None, office="Mee-Seva centre / Gram Panchayat", portal="cheyutha.telangana.gov.in",
        extra_doc="medical"),
}

# Document names per language
DOC_NAMES = {
    "aadhaar": {"en": "Aadhaar card", "te": "ఆధార్ కార్డు", "roman": "Aadhaar card"},
    "ration": {"en": "Ration card", "te": "రేషన్ కార్డు", "roman": "Ration card"},
    "bank": {"en": "Bank passbook (first page)", "te": "బ్యాంక్ పాస్‌బుక్ (మొదటి పేజీ)", "roman": "Bank passbook (first page)"},
    "photo": {"en": "Passport size photo", "te": "పాస్‌పోర్ట్ సైజ్ ఫోటో", "roman": "Passport size photo"},
    "death": {"en": "Husband's death certificate", "te": "భర్త మరణ ధృవీకరణ పత్రం", "roman": "Bharta marana certificate"},
    "sadarem": {"en": "SADAREM disability certificate", "te": "SADAREM వైకల్య ధృవీకరణ పత్రం", "roman": "SADAREM disability certificate"},
    "medical": {"en": "Medical documents for the condition", "te": "పరిస్థితికి సంబంధించిన వైద్య పత్రాలు", "roman": "Vaidya patralu (medical documents)"},
}

TE_CHARS = re.compile(r"[\u0C00-\u0C7F]")
DISTRESS_WORDS = ("suicide", "end my life", "kill myself", "no reason to live", "chachipoyela", "brathikaler")
FRAUD_WORDS = ("cheated", "fraud", "lost money", "middleman took")


def msg(session, key):
    return CATALOG[session.lang][key]


def fill(template, **values):
    out = template
    for k, v in values.items():
        out = out.replace("{" + k + "}", str(v))
    return out


def docs_for_category(category):
    keys = ["aadhaar", "ration", "bank", "photo"]
    extra = {"widow": "death", "disabled": "sadarem", "chronic": "medical"}.get(category)
    if extra:
        keys.append(extra)
    return keys


class Session:
    def __init__(self):
        self.lang = "en"          # en / te / roman
        self.phase = "lang"      # lang, state, menu, pension_cat, questions, name, district, docs, track, escalated
        self.state_code = None    # AP / TS
        self.category = None
        self.questions = []      # list of catalog keys still to ask
        self.answers = {}
        self.name = None
        self.district = None
        self.doc_keys = []
        self.doc_index = 0

    # ---- helpers ----------------------------------------------------------
    def scheme(self):
        return SCHEMES[(self.state_code, self.category)]

    def scheme_card(self):
        s = self.scheme()
        return "\n".join([
            msg(self, "lbl_scheme") + ": " + s["name"],
            msg(self, "lbl_amount") + ": " + s["amount"],
            msg(self, "lbl_office") + ": " + s["office"],
            msg(self, "lbl_portal") + ": " + s["portal"],
        ])

    def ask_current_question(self):
        return msg(self, self.questions[0])


# ---------------------------------------------------------------------------
# The conversation engine
# ---------------------------------------------------------------------------
def handle(session, text):
    """Process one inbound message; return a list of outbound messages."""
    t = text.strip()
    low = t.lower()

    # --- global interrupts -------------------------------------------
    if session.phase == "escalated":
        if low == "menu":
            session.phase = "menu"
            return [msg(session, "main_menu")]
        return []  # a human agent owns this conversation now

    if low in ("menu", "మెనూ"):
        session.phase = "menu"
        return [msg(session, "main_menu")]

    if any(w in low for w in DISTRESS_WORDS):
        session.phase = "escalated"
        return [msg(session, "distress")]

    if any(w in low for w in FRAUD_WORDS):
        session.phase = "escalated"
        return [msg(session, "escalate")]

    replies = []
    prev_lang = session.lang
    otp_hit = any(w in low for w in ("otp", "pin", "password", "పాస్‌వర్డ్"))
    if otp_hit:
        replies.append(msg(session, "otp_warning"))

    # language switching (v1: explicit words)
    if "english" in low:
        session.lang = "en"
    elif "tenglish" in low or "roman" in low:
        session.lang = "roman"
    elif "telugu" in low:
        session.lang = "te"
    lang_switched = session.lang != prev_lang

    # --- phase dispatch -----------------------------------------------
    if session.phase == "lang":
        if TE_CHARS.search(t):
            session.lang = "te"
            session.phase = "state"
            return [msg(session, "choose_state")]
        if lang_switched:
            session.phase = "state"
            return [msg(session, "choose_state")]
        if low == "1":
            session.lang = "en"
        elif low == "2":
            session.lang = "te"
        else:
            return [msg(session, "greet")]
        session.phase = "state"
        return [msg(session, "choose_state")]

    if session.phase == "state":
        if low == "1":
            session.state_code = "AP"
        elif low == "2":
            session.state_code = "TS"
        else:
            return [msg(session, "choose_state")]
        session.phase = "menu"
        return [msg(session, "main_menu"), msg(session, "menu_hint")]

    if session.phase == "menu":
        if low == "1":
            session.phase = "pension_cat"
            return replies + [msg(session, "pension_menu")]
        if low == "2":
            session.phase = "cert_info"
            return [msg(session, "certs_menu")]
        if low == "3":
            session.phase = "tax_info"
            return [msg(session, "tax_menu")]
        if low == "4":
            session.phase = "track"
            return [msg(session, "track_intro")]
        if low == "5":
            session.phase = "escalated"
            return replies + [msg(session, "escalate")]
        return replies + [msg(session, "out_of_scope")]

    if session.phase == "pension_cat":
        if low in ("1", "2", "3", "4"):
            session.category = {"1": "old_age", "2": "widow", "3": "disabled", "4": "chronic"}[low]
            s = session.scheme()
            qs = []
            if s["min_age"] is not None:
                qs.append("ask_age")
            extra = {"widow": "ask_death_cert", "disabled": "ask_sadarem", "chronic": "ask_medical"}.get(session.category)
            if extra:
                qs.append(extra)
            qs += ["ask_ration", "ask_bank"]
            session.questions = qs
            session.answers = {}
            session.phase = "questions"
            return [session.ask_current_question()]
        return replies + [msg(session, "pension_menu")]

    if session.phase == "cert_info":
        key = {"1": "cert_income", "2": "cert_caste", "3": "cert_birth", "4": "cert_residence"}.get(low)
        if key:
            return replies + [msg(session, key), msg(session, "menu_hint")]
        return replies + [msg(session, "certs_menu")]

    if session.phase == "tax_info":
        key = {"1": "tax_it", "2": "tax_gst"}.get(low)
        if key:
            return replies + [msg(session, key), msg(session, "menu_hint")]
        return replies + [msg(session, "tax_menu")]

    if session.phase == "questions":
        q = session.questions[0]
        if q == "ask_age":
            m = re.search(r"\d+", t)
            if not m:
                return replies + [msg(session, "ask_age")]
            session.answers["age"] = int(m.group())
        elif q in ("ask_ration",):
            if low not in ("1", "2", "3"):
                return replies + [msg(session, q)]
            session.answers["ration"] = low
        else:  # yes/no questions
            if low not in ("1", "2", "yes", "no", "y", "n"):
                return replies + [msg(session, q)]
            session.answers[q] = low.startswith(("1", "y"))
        session.questions.pop(0)
        if session.questions:
            return replies + [session.ask_current_question()]
        # all answered -> evaluate eligibility
        return replies + evaluate(session)

    if session.phase == "name":
        session.name = t
        session.phase = "district"
        return replies + [msg(session, "ask_district")]

    if session.phase == "district":
        session.district = t
        session.doc_keys = docs_for_category(session.category)
        session.doc_index = 0
        session.phase = "docs"
        listing = "\n".join("{}. {}".format(i + 1, DOC_NAMES[k][session.lang]) for i, k in enumerate(session.doc_keys))
        return replies + [fill(msg(session, "checklist"), docs=listing)]

    if session.phase == "docs":
        if "blur" in low or "blurry" in low:
            doc = DOC_NAMES[session.doc_keys[session.doc_index]][session.lang]
            return [fill(msg(session, "doc_problem"), doc=doc)]
        if low == "done" or session.doc_index >= len(session.doc_keys):
            return replies + finish_case(session)
        doc = DOC_NAMES[session.doc_keys[session.doc_index]][session.lang]
        session.doc_index += 1
        if session.doc_index >= len(session.doc_keys):
            return replies + [fill(msg(session, "doc_ok"), doc=doc, next=msg(session, "doc_all_done"))] + finish_case(session)
        nxt = DOC_NAMES[session.doc_keys[session.doc_index]][session.lang]
        return replies + [fill(msg(session, "doc_ok"), doc=doc, next=nxt)]

    if session.phase == "track":
        ref = low.upper().replace(" ", "")
        case = load_cases().get(ref)
        if not case:
            return [msg(session, "track_not_found")]
        minutes = (time.time() - case["created"]) / 60.0
        if minutes < 1:
            st = msg(session, "st_received")
        elif minutes < 2:
            st = msg(session, "st_verify")
        elif minutes < 3:
            st = msg(session, "st_recommended")
        else:
            st = msg(session, "st_approved")
        session.phase = "menu"
        return [fill(msg(session, "track_status"), ref=ref, status=st)]

    # fallthrough (should not happen)
    session.phase = "menu"
    return [msg(session, "main_menu")]


def evaluate(session):
    s = session.scheme()
    a = session.answers
    if s["min_age"] is not None and a.get("age", 0) < s["min_age"]:
        session.phase = "menu"
        return [fill(msg(session, "not_eligible"), reason=msg(session, "reason_age")), msg(session, "menu_hint")]
    if a.get("ration") not in ("1",):
        session.phase = "menu"
        return [fill(msg(session, "not_eligible"), reason=msg(session, "reason_ration")), msg(session, "menu_hint")]
    if "ask_death_cert" in a and not a["ask_death_cert"]:
        session.phase = "menu"
        return [fill(msg(session, "not_eligible"), reason=msg(session, "reason_doc")), msg(session, "menu_hint")]
    if "ask_sadarem" in a and not a["ask_sadarem"]:
        session.phase = "menu"
        return [fill(msg(session, "not_eligible"), reason=msg(session, "reason_doc")), msg(session, "menu_hint")]
    if "ask_medical" in a and not a["ask_medical"]:
        session.phase = "menu"
        return [fill(msg(session, "not_eligible"), reason=msg(session, "reason_doc")), msg(session, "menu_hint")]
    if not a.get("ask_bank", True):
        session.phase = "menu"
        return [fill(msg(session, "not_eligible"), reason=msg(session, "reason_bank")), msg(session, "menu_hint")]
    session.phase = "name"
    return [msg(session, "eligible"), session.scheme_card(), msg(session, "ask_name")]


# ---------------------------------------------------------------------------
# Case store (v1: local JSON file; later: Postgres + real status feeds)
# ---------------------------------------------------------------------------
_cases_lock = threading.Lock()


def load_cases():
    try:
        with open(CASES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_case(case):
    with _cases_lock:
        cases = load_cases()
        n = len(cases) + 1
        ref = "SM-{}".format(1000 + n)
        cases[ref] = case
        with open(CASES_FILE, "w", encoding="utf-8") as f:
            json.dump(cases, f, ensure_ascii=False, indent=2)
    return ref


def finish_case(session):
    docs = ", ".join(DOC_NAMES[k][session.lang] for k in session.doc_keys[:session.doc_index]) or "-"
    case = dict(
        name=session.name, district=session.district,
        state=session.state_code, category=session.category,
        scheme=session.scheme()["name"], created=time.time(),
    )
    ref = save_case(case)
    session.phase = "menu"
    s = session.scheme()
    summary = fill(msg(session, "summary"), name=session.name, scheme=s["name"],
                   district=session.district, docs=docs, office=s["office"],
                   portal=s["portal"], ref=ref)
    return [summary, msg(session, "menu_hint")]


# ---------------------------------------------------------------------------
# Mode: interactive terminal chat
# ---------------------------------------------------------------------------
def run_chat():
    print("=" * 62)
    print(" Seva Mitra - interactive chat (type 'quit' to exit, 'restart' to reset)")
    print("=" * 62)
    session = Session()
    print("\nCitizen:\n  (start the conversation, e.g. type: hi)\n")
    while True:
        try:
            text = input("Citizen > ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not text:
            continue
        if text.lower() == "quit":
            break
        if text.lower() == "restart":
            session = Session()
            print("  [session reset]\n")
            continue
        for reply in handle(session, text):
            print("\nSeva Mitra >\n" + reply + "\n")


# ---------------------------------------------------------------------------
# Mode: scripted demo (3 citizens, 3 language modes)
# ---------------------------------------------------------------------------
def run_demo():
    def show(session, text, note=""):
        print("\n--- Citizen: {!r} {}".format(text, note))
        for reply in handle(session, text):
            print("  Seva Mitra:\n" + _indent(reply))

    print("=" * 70)
    print(" DEMO 1 - English - AP old age pension (eligible, full application)")
    print("=" * 70)
    s1 = Session()
    for t in ["hi", "1", "1", "1", "1", "62", "1", "1", "Lakshmi", "Krishna",
              "aadhaar.jpg", "ration.jpg", "passbook.jpg", "photo.jpg"]:
        show(s1, t)
    print("\n--- (later, tracking the application) ---")
    ref = sorted(load_cases())[-1]
    s1.phase = "menu"
    show(s1, "4")
    show(s1, ref)

    print("\n" + "=" * 70)
    print(" DEMO 2 - Telugu script - TS widow pension (full application)")
    print("=" * 70)
    s2 = Session()
    for t in ["హాయ్", "2", "1", "2", "45", "1", "1", "1", "సుశీల", "ఖమ్మం",
              "aadhaar.jpg", "ration.jpg", "bank.jpg", "photo.jpg", "death.jpg"]:
        show(s2, t)

    print("\n" + "=" * 70)
    print(" DEMO 3 - Romanised Telugu - AP old age pension (age not eligible)")
    print("=" * 70)
    s3 = Session()
    for t in ["hi, naku telugu l typing estaru, roman telugu please", "1", "1", "1", "55", "1", "1"]:
        show(s3, t)
    show(s3, "menu")

    print("\n" + "=" * 70)
    print(" DEMO 4 - Safety rails - OTP question and out-of-scope query")
    print("=" * 70)
    s4 = Session()
    for t in ["hi", "1", "1"]:
        show(s4, t)
    show(s4, "what is my otp? someone asked me to share my pin", note="(OTP guardrail)")
    show(s4, "can you book me a flight ticket", note="(out of scope)")
    print("\nDemo complete. Cases saved to", CASES_FILE)


def _indent(text):
    return "\n".join("    " + line for line in text.splitlines())


# ---------------------------------------------------------------------------
# Mode: WhatsApp-style webhook server
# ---------------------------------------------------------------------------
SESSIONS = {}  # phone -> Session


class WebhookHandler(BaseHTTPRequestHandler):
    def _json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            self._json(200, {"status": "ok"})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/webhook":
            self._json(404, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            self._json(400, {"error": "invalid json"})
            return
        # Accepts a simplified WhatsApp Cloud API shape:
        #   {"from": "+91...", "text": "hi"}
        # or the full entry[]->changes[]->value->messages[] structure.
        sender, text = self._extract(payload)
        if not sender or text is None:
            self._json(400, {"error": "expected fields: from, text"})
            return
        session = SESSIONS.setdefault(sender, Session())
        replies = handle(session, text)
        print("[{}] {} -> {} reply(ies)".format(sender, text[:40], len(replies)))
        self._json(200, {"replies": replies})

    @staticmethod
    def _extract(payload):
        if "from" in payload and "text" in payload:
            return payload.get("from"), payload.get("text")
        try:  # Meta Cloud API shape
            m = payload["entry"][0]["changes"][0]["value"]["messages"][0]
            return m.get("from"), m.get("text", {}).get("body")
        except (KeyError, IndexError, TypeError):
            return None, None

    def log_message(self, fmt, *args):
        pass  # quieter logs; we print the essentials ourselves


def run_server(port=8787):
    server = ThreadingHTTPServer(("0.0.0.0", port), WebhookHandler)
    print("Seva Mitra webhook server on http://0.0.0.0:{}".format(port))
    print("  POST /webhook  {\"from\": \"+91XXXXX\", \"text\": \"hi\"}  ->  {\"replies\": [...]}")
    print("  GET  /health")
    print("Point your WhatsApp provider (Gupshup / Twilio / Meta sandbox) here.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nserver stopped")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "chat"
    if mode == "chat":
        run_chat()
    elif mode == "demo":
        run_demo()
    elif mode == "serve":
        run_server(int(sys.argv[2]) if len(sys.argv) > 2 else 8787)
    else:
        print(__doc__)
