from fastapi import FastAPI, HTTPException, Depends, status
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import httpx
import os
import random
import sqlite3
import json
import re
import asyncio
from datetime import datetime
from typing import List, Optional, Dict
from passlib.context import CryptContext
import google.generativeai as genai
import base64
import traceback
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="FoodGuard Elite API")

# Configuration
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "AIzaSyCf0SE8IetEWv5EchFUgKGcBiAZRGE9q74")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

# Supabase Client
supabase: Optional[Client] = None
if SUPABASE_URL and SUPABASE_KEY:
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    print("DB: Connected to Supabase Cloud")
else:
    print("DB: Using local SQLite database")

@app.get("/", response_class=HTMLResponse)
async def read_index():
    return FileResponse('static/index.html')

# Setup DB
DB_PATH = "foodguard.db"

# Helper: Database Access (Dual Mode)
def db_get_user(username: str):
    if supabase:
        res = supabase.table("users").select("*").eq("username", username).execute()
        return res.data[0] if res.data else None
    else:
        conn = sqlite3.connect(DB_PATH); cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE username=?", (username,))
        row = cursor.fetchone()
        conn.close()
        if row: return {"username": row[0], "password": row[1], "settings": row[2], "last_active": row[3]}
        return None

def db_update_last_active(username: str):
    now = datetime.now().isoformat()
    if supabase:
        supabase.table("users").update({"last_active": now}).eq("username", username).execute()
    else:
        conn = sqlite3.connect(DB_PATH); cursor = conn.cursor()
        cursor.execute("UPDATE users SET last_active=? WHERE username=?", (now, username))
        conn.commit(); conn.close()

def db_save_history(username: str, barcode: str, product_name: str, status: str, score: int):
    now = datetime.now().isoformat()
    if supabase:
        supabase.table("history").insert({
            "username": username, "barcode": barcode, 
            "product_name": product_name, "status": status, 
            "score": score, "timestamp": now
        }).execute()
        supabase.table("users").update({"last_active": now}).eq("username", username).execute()
    else:
        conn = sqlite3.connect(DB_PATH); cursor = conn.cursor()
        cursor.execute("INSERT INTO history (username, barcode, product_name, status, score, timestamp) VALUES (?, ?, ?, ?, ?, ?)",
                       (username, barcode, product_name, status, score, now))
        cursor.execute("UPDATE users SET last_active=? WHERE username=?", (now, username))
        conn.commit(); conn.close()

def db_get_history(username: str, limit=50):
    if supabase:
        res = supabase.table("history").select("*").eq("username", username).order("timestamp", desc=True).limit(limit).execute()
        return res.data
    else:
        conn = sqlite3.connect(DB_PATH); cursor = conn.cursor()
        cursor.execute("SELECT barcode, product_name, status, score, timestamp FROM history WHERE username=? ORDER BY timestamp DESC LIMIT ?", (username, limit))
        rows = cursor.fetchall()
        conn.close()
        return [{"barcode": r[0], "name": r[1], "status": r[2], "score": r[3], "timestamp": r[4]} for r in rows]

def init_db():
    if not supabase:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('''CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, password TEXT, settings TEXT)''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS history (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, barcode TEXT, product_name TEXT, status TEXT, score INTEGER, timestamp DATETIME, FOREIGN KEY(username) REFERENCES users(username))''')
        cursor.execute("PRAGMA table_info(users)")
        columns = [column[1] for column in cursor.fetchall()]
        if 'last_active' not in columns:
            cursor.execute("ALTER TABLE users ADD COLUMN last_active DATETIME")
        conn.commit(); conn.close()
    else:
        print("DB: Initialization skipped (Using Cloud Tables)")

init_db()

# Security
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
def get_password_hash(password): return pwd_context.hash(password)
def verify_password(plain_password, hashed_password): return pwd_context.verify(plain_password, hashed_password)

# Comprehensive Additive Database (Clinical Profiles)
# Classification: safe (Green), warning (Yellow/Orange), danger (Red)
ADDITIVES_DICT = {
    # COLORANTES (E100-E199)
    "tartrazina": {
        "code": "E102", "safety": "danger", "name": "Tartrazina", 
        "harm": "Colorante azoico vinculado a hiperactividad infantil y asma bronquial.",
        "harm_detail": "Su estructura química libera aminas aromáticas que pueden desencadenar la liberación de histamina. Se observa un impacto directo en la permeabilidad de la barrera hematoencefálica en modelos de desarrollo temprano.",
        "risk_profile": "🧬 Genotoxicidad / 🧠 Neuroconductual", "adi_warning": "⚠️ Muy fácil de superar", 
        "study": "EFSA / Univ. Southampton: Vínculo confirmado con falta de concentración infantil.",
        "study_detail": "Estudio doble ciego aleatorizado (Lancet) que demostró un aumento significativo de comportamientos disruptivos en niños que consumieron mezclas de colorantes incluyendo E102."
    },
    "amarillo ocaso": {
        "code": "E110", "name": "Amarillo Ocaso FCF", "safety": "danger", 
        "harm": "Daña el sistema inmunológico y causa déficit de atención por neurotoxicidad.",
        "harm_detail": "Actúa como un disruptor inmunológico al interferir con la respuesta de los leucocitos. En estudios celulares, se ha observado una inhibición parcial del crecimiento celular.",
        "risk_profile": "🧬 Genotoxicity / 🛡️ Inmunotoxicidad", "adi_warning": "⚠️ Riesgo acumulativo", 
        "study": "JECFA: Bajo revisión constante por potencial genotóxico en células mamíferas.",
        "study_detail": "Evaluaciones de la EFSA indican que los niños pueden superar la Ingesta Diaria Admisible (IDA) consumiendo solo un par de productos industriales altamente coloreados."
    },
    "rojo allura": {
        "code": "E129", "name": "Rojo Allura AC", "safety": "danger", 
        "harm": "Inducción de colitis y cambios profundos en la barrera mucosa intestinal.",
        "harm_detail": "Altera la microbiota intestinal aumentando bacterias pro-inflamatorias. Daña directamente las proteínas que mantienen unidas las células del colon (Tight Junctions).",
        "risk_profile": "🦠 Microbiota / 🧬 Inflamatorio", "adi_warning": "⚠️ Ultraprocesados", 
        "study": "Nature Communications (2022): El consumo prolongado daña directamente la mucosa del colon.",
        "study_detail": "La exposición temprana desencadena una susceptibilidad aumentada a la enfermedad inflamatoria intestinal (EII) al degradar la capa protectora de mucina."
    },
    "caramelo sulfito": {"code": "E150d", "name": "Caramelo de Sulfito Amónico", "safety": "danger", "harm": "Contiene 4-MEI, subproducto de fabricación clasificado como carcinógeno.", "risk_profile": "🧬 Cáncer / 🩸 Médula Ósea", "adi_warning": "❌ Evitar consumo diario", "study": "IARC (OMS): Clasificado en el Grupo 2B (Posible carcinógeno humano)."},
    "dioxido de titanio": {
        "code": "E171", "name": "Dióxido de Titanio", "safety": "danger", 
        "harm": "Nanopartículas que penetran el núcleo celular causando fragmentación del ADN.",
        "harm_detail": "Debido a su tamaño nanométrico, las partículas cruzan las membranas celulares y se acumulan en órganos como el hígado y bazo, provocando estrés oxidativo crónico.",
        "risk_profile": "🧬 Genotoxicidad ADN / 🫀 Vascular", "adi_warning": "🚫 Prohibido en la UE", 
        "study": "EFSA 2021: Dictamen final de inseguridad al no poder descartar daño genético irreversible.",
        "study_detail": "Basado en más de 200 estudios científicos que demuestran que no existe un nivel seguro de ingesta para prevenir la genotoxicidad por acumulación de partículas."
    },
    "carmin": {"code": "E120", "name": "Carmín / Ácido Carmínico", "safety": "danger", "harm": "Colorante derivado de insectos. Riesgo de shock anafiláctico y asma.", "risk_profile": "🧪 Alergia Grave / 🛡️ Inmune", "adi_warning": "⚠️ Evitar en alérgicos", "study": "EFSA: Casos confirmados de reacciones alérgicas graves mediadas por proteínas de insecto."},
    "azul brillante": {"code": "E133", "name": "Azul Brillante FCF", "safety": "danger", "harm": "Colorante sintético vinculado a hiperactividad y potencial neurotoxicidad.", "risk_profile": "🧠 Neuroconductual / 🧪 Sintético", "adi_warning": "⚠️ Evitar en niños", "study": "FDA: Bajo vigilancia por asociación con THDA en subgrupos sensibles."},
    "eritrosina": {"code": "E127", "name": "Eritrosina", "safety": "danger", "harm": "Interfiere con el metabolismo del yodo y la función tiroidea.", "risk_profile": "🦋 Tiroides / 🧬 ADN", "adi_warning": "❌ Evitar", "study": "EFSA: Restringido a usos muy específicos por riesgo hormonal."},

    # CONSERVANTES (E200-E299)
    "sorbato de potasio": {"code": "E202", "name": "Sorbato de Potasio", "safety": "warning", "harm": "Genotóxico para linfocitos humanos en dosis altas. Riesgo por acumulación.", "risk_profile": "🧬 Linfocitos / 🧪 Irritación Celular", "adi_warning": "⚠️ Muy común", "study": "Toxicology Reports: Evidencia de inducción de estrés oxidativo en mitocondrias cerebrales."},
    "benzoato de sodio": {"code": "E211", "name": "Benzoato de Sodio", "safety": "danger", "harm": "En combinación con Vitamina C genera benceno (cancerígeno). Daño mitocondrial.", "risk_profile": "🧬 Daño ADN / ⚡ Mitotoxicidad", "adi_warning": "❌ Riesgo en bebidas ácidas", "study": "Univ. Sheffield: Vinculado a la inactivación de genes vitales en la mitocondria humana."},
    "nitrito de sodio": {
        "code": "E250", "name": "Nitrito de Sodio", "safety": "danger", 
        "harm": "Formación de nitrosaminas en el estómago. Vínculo directo con cáncer colorrectal.",
        "harm_detail": "En el entorno ácido del estómago, los nitritos reaccionan con aminas de la carne para formar Nitrosaminas, potentes carcinógenos que dañan el código genético del epitelio digestivo.",
        "risk_profile": "🧬 Carcinogénesis ADN / 🩸 Hemoglobina", "adi_warning": "❌ Riesgo extremo en carnes", 
        "study": "ANSES 2022: Informe final confirmando el vínculo entre nitritos y riesgo de cáncer colorrectal.",
        "study_detail": "La OMS clasifica la carne procesada con nitritos en el Grupo 1 (Carcinógeno para humanos), compartiendo categoría con el tabaco y el amianto."
    },
    "sulfito de sodio": {"code": "E221", "name": "Sulfitos", "safety": "danger", "harm": "Destruye la vitamina B1. Altamente alérgeno, provoca crisis asmáticas.", "risk_profile": "🧪 Alergia / 🛡️ Vitamina B1", "adi_warning": "❌ Alerta Asma", "study": "EFSA: Obligatorio declarar a partir de 10mg/kg por riesgo de shock."},

    # ANTIOXIDANTES Y FOSFATOS (E300-E399)
    "fosfatos": {"code": "E339-E452", "name": "Fosfatos Industriales", "safety": "warning", "harm": "Calcificación vascular prematura y aceleración del envejecimiento orgánico.", "risk_profile": "🫀 Cardiovascular / 🚿 Renal / 🦴 Huesos", "adi_warning": "⚠️ Supera DDA fácilmente", "study": "Freiburg Univ. / INSERM: Asociación con fallo renal agudo en consumidores frecuentes."},
    "acido fosforico": {"code": "E338", "name": "Ácido Fosfórico", "safety": "danger", "harm": "Desmineralización ósea profunda y cálculos renales por exceso de fósforo.", "risk_profile": " Huesos / 🚿 Renal", "adi_warning": "❌ Riesgo en refrescos", "study": "American Journal of Clinical Nutrition: Vínculo con baja densidad ósea en mujeres."},
    "bha": {"code": "E320", "name": "BHA (Butilhidroxianisol)", "safety": "danger", "harm": "Posible carcinógeno y alterador endocrino. Daña el sistema hormonal.", "risk_profile": "🧬 Cáncer / 🦋 Endocrino", "adi_warning": "⚠️ Muy persistente", "study": "IARC: Clasificado como 2B. NIEHS: Razonablemente anticipado como carcinógeno humano."},

    # ESPESANTES Y EMULGENTES (E400-E499)
    "carragenano": {
        "code": "E407", "name": "Carragenanos", "safety": "danger", 
        "harm": "Inflamación intestinal sistémica y potencial desarrollo de ulceraciones de colon.",
        "harm_detail": "Inactiva la enzima sulfatasa ácida intestinal, lo que provoca la degradación del moco protector y permite que las bacterias penetren en la lámina propia del intestino.",
        "risk_profile": "🦠 Microbiota / 🧬 Inflamación Mucosa", "adi_warning": "❌ Evitar en sensibilidad gástrica", 
        "study": "Int J Mol Sci: Demostró inducir intolerancia a la glucosa y disbiosis intestinal profunda.",
        "study_detail": "Estudios en humanos muestran que su exclusión de la dieta mejora drásticamente los síntomas de pacientes con colitis ulcerosa en remisión."
    },
    "monogliceridos": {"code": "E471", "name": "Mono y Diglicéridos", "safety": "warning", "harm": "Emulsificantes industriales vinculados a la ruptura de la barrera intestinal.", "risk_profile": " Cardiovascular / 🩹 Permeabilidad", "adi_warning": "⚠️ Presente en ultraprocesados", "study": "The BMJ (2023): Landmark study (INSERM) vinculando E471 con mayor riesgo de infarto."},
    "polisorbato 80": {"code": "E433", "name": "Polisorbato 80", "safety": "danger", "harm": "Detergente industrial que 'limpia' la mucosa protectora del intestino.", "risk_profile": " Barrera Intestinal /  Microbiota", "adi_warning": "⚠️ Riesgo Crohn/Colitis", "study": "Nature: Demostró promover la inflamación crónica en modelos animales."},
    "carboximetilcelulosa": {
        "code": "E466", "name": "CMC / Goma Celulosa", "safety": "danger", 
        "harm": "Altera drásticamente la composición de la microbiota hacia un perfil inflamatorio.",
        "harm_detail": "Reduce la distancia entre las bacterias del lumen y el epitelio intestinal, forzando al sistema inmune a estar en alerta constante, lo que deriva en síndrome metabólico.",
        "risk_profile": "🦠 Microbiota / 🩹 Inflamación", "adi_warning": "⚠️ Evitar en UPFs", 
        "study": "Gastroenterology: El consumo humano altera la composición de bacterias intestinales en solo 11 días.",
        "study_detail": "Primer estudio clínico controlado en humanos que demuestra pérdida de diversidad bacteriana y depleción de metabolitos beneficiosos para la salud."
    },
    "difosfatos": {"code": "E450", "name": "Difosfatos / Polifosfatos", "safety": "danger", "harm": "Interfieren con la absorción de calcio. Riesgo vascular severo.", "risk_profile": " Vascular / 🦴 Minerales", "adi_warning": "⚠️ Riesgo de calcificación", "study": "EFSA 2019: Re-evaluación que redujo la ingesta aceptable por riesgos renales."},
    "gomas": {"code": "E410-E415", "name": "Gomas (Garrofín, Guar, Xantana)", "safety": "warning", "harm": "Alteración del grosor de la mucina intestinal, facilitando paso de toxinas.", "risk_profile": "🦠 Microbiota / 🩹 Mucosa", "adi_warning": "⚠️ Muy frecuentes", "study": "Cell Host & Microbe: Observación de adelgazamiento de la barrera protectora intestinal."},
    "glicerol": {"code": "E422", "name": "Glicerol / Glicerina", "safety": "warning", "harm": "Solvente industrial refinado. Marcador de alimentos ultra-transformados.", "risk_profile": "🧪 Refinado / 🚽 Osmótico", "adi_warning": "⚠️ Indicador industrial", "study": "EFSA 2023: Re-evaluación prioritaria para limitar impurezas como la acroleína."},
    "sorbitol": {"code": "E420", "name": "Sorbitoles", "safety": "warning", "harm": "Poliol edulcorante. Causa hinchazón, gases y alteración de flora bacteriana.", "risk_profile": "🦠 Microbiota / 🚽 Malestar", "adi_warning": "🚫 Prohibido en bebidas infantiles", "study": "Gastroenterology: Asociación con disbiosis intestinal profunda en consumo diario."},
    "e420i": {"code": "E420i", "name": "Sorbitol", "safety": "warning", "harm": "Utilizado para mantener humedad. Perturba la microbiota intestinal.", "risk_profile": "🦠 Microbiota / 🚽 Digestivo", "adi_warning": "⚠️ Riesgo limitado", "study": "EFSA: Evaluación técnica de polioles y salud gástrica."},
    "pectina": {"code": "E440", "name": "Pectinas", "safety": "warning", "harm": "Aunque de origen vegetal, su extracción industrial la marca como riesgo limitado.", "risk_profile": "🦠 Microbiota", "adi_warning": "⚠️ Riesgo limitado", "study": "EFSA: Evaluación de seguridad para uso alimentario."},

    # GASIFICANTES Y REFINADOS (E500+)
    "bicarbonato": {"code": "E500", "safety": "warning", "name": "Bicarbonato de Sodio", "harm": "Sal refinada industrial. Indica producto altamente transformado.", "risk_profile": "🧪 Industrial / ⚖️ Balance pH", "adi_warning": "⚠️ Consumo limitado", "study": "EFSA 2024 (Call for Data): Vigilancia ante impurezas metálicas (Aluminio) en aditivos minerales."},
    "carbonatos": {"code": "E500/E503", "safety": "warning", "name": "Carbonatos Sódicos/Amónicos", "harm": "Químicos de horneado industrial. Irritantes para el estómago.", "risk_profile": "🚽 Digestivo / 🧪 Químico", "adi_warning": "⚠️ Ultraprocesado", "study": "EFSA 2023: Evaluación de seguridad para lactantes y niños pequeños."},
    "carbonatos de sodio": {"code": "E500", "safety": "warning", "name": "Carbonatos de Sodio", "harm": "Gasificante industrial. Riesgo limitado para la salud.", "risk_profile": "🧪 Industrial", "adi_warning": "⚠️ Riesgo limitado", "study": "EFSA."},
    "aroma": {"code": "AROMA", "safety": "warning", "name": "Aromas / Aromatizantes", "harm": "Opacidad clínica. Puede incluir disolventes y conservantes no declarados.", "risk_profile": "🧪 Opacidad / 💡 Desconocido", "adi_warning": "⚠️ Evitar en niños", "study": "INSERM (NutriNet-Santé): Consumo de aromas industriales asociado a mayor riesgo metabólico."},
    "aroma artificial": {"code": "AROMA", "safety": "warning", "name": "Aroma Artificial", "harm": "Sustancias químicas de síntesis. Falta de transparencia en composición.", "risk_profile": "🧪 Sintético / 🧪 Opacidad", "adi_warning": "⚠️ Riesgo acumulativo", "study": "INSERM: Los aromas sintéticos forman parte del conjunto de riesgo de alimentos ultraprocesados."},

    # POTENCIADORES DEL SABOR
    "glutamato monosodico": {
        "code": "E621", "safety": "danger", "name": "Glutamato Monosódico (MSG)", 
        "harm": "Neuroexcitotoxina. Vinculado a migrañas y sobreestimulación del apetito.",
        "harm_detail": "Sobreestimula los receptores de glutamato en el cerebro, lo que puede causar fatiga neuronal. Además, altera la señalización de leptina, la hormona que nos dice que estamos saciados.",
        "risk_profile": "🧠 Neurosensibilidad / 🧪 Excitotoxicidad", "adi_warning": "⚠️ Complejo de síntomas MSG", 
        "study": "FDA / FASEB: Reconoce 'Complejo de Síntomas MSG' (dolor de cabeza, palpitaciones) en dosis de 3g+.",
        "study_detail": "Uso extensivo en la industria para enmascarar ingredientes de baja calidad y forzar el consumo repetitivo mediante la excitación de los receptores umami."
    },

    # EDULCORANTES
    "aspartamo": {"code": "E951", "safety": "danger", "name": "Aspartamo", "harm": "Neurotoxicidad y alteración de los mecanismos de saciedad y glucosa sanguínea.", "risk_profile": "🧠 Neuro / ⚖️ Insulina / 🧬 DNA", "adi_warning": "❌ IARC 2023: 2B", "study": "IARC 2023 / INSERM: Clasificado como posiblemente cancerígeno con evidencia en cáncer de mama."},

    # SEGUROS (Verificados)
    "lecitina": {"code": "E322", "safety": "safe", "name": "Lecitina (Soja/Girasol)", "harm": "Lípido esencial beneficioso para la función neuronal y hepática.", "harm_detail": "Fuente natural de colina e inositol. Nutrientes vitales para la formación de membranas celulares y el transporte de grasas.", "risk_profile": "🧠 Salud / ✅ Seguro", "adi_warning": "✅ Sin límite", "study": "EFSA: Evaluación positiva recurrente por beneficios en el perfil lipídico.", "study_detail": "Dictámenes técnicos constantes confirman su seguridad absoluta y su rol como nutriente esencial en la dieta humana."},
    "e322i": {"code": "E322i", "safety": "safe", "name": "Lecitina de Soja", "harm": "Emulgente seguro de origen vegetal.", "risk_profile": "✅ Seguro", "adi_warning": "✅ Seguro", "study": "EFSA Panel on Food Additives."},
    "acido ascorbico": {"code": "E300", "safety": "safe", "name": "Vitamina C", "harm": "Antioxidante hidrosoluble natural. Factor clave para el colágeno.", "risk_profile": "🛡️ Celular / ✅ Seguro", "adi_warning": "✅ Seguro", "study": "Nutriente esencial clínica."},
    "acido citrico": {"code": "E330", "safety": "safe", "name": "Ácido Cítrico", "harm": "Regulador de acidez natural y seguro en dosis convencionales.", "harm_detail": "Intermediario clave en el ciclo de Krebs. Nuestro cuerpo lo procesa de forma natural y eficiente.", "risk_profile": "⚖️ Metabolismo / ✅ Seguro", "adi_warning": "✅ Seguro", "study": "Molécula metabólica natural (Kreb's).", "study_detail": "Evaluación de la EFSA confirma que no hay riesgos de seguridad, incluso en ingestas elevadas, dada su naturaleza endógena."}
}

# Simplified database for code-based lookup
ADDITIVES_DB = {v["code"]: v for v in ADDITIVES_DICT.values() if "code" in v}
# Supplement with individual codes for multi-code entries
ADDITIVES_DB["E410"] = ADDITIVES_DICT["gomas"] 
ADDITIVES_DB["E412"] = ADDITIVES_DICT["gomas"]
ADDITIVES_DB["E415"] = ADDITIVES_DICT["gomas"]
ADDITIVES_DB["E500"] = ADDITIVES_DICT["bicarbonato"]
ADDITIVES_DB["E503"] = ADDITIVES_DICT["carbonatos"]
ADDITIVES_DB["E422"] = ADDITIVES_DICT["glicerol"]
ADDITIVES_DB["E420"] = ADDITIVES_DICT["sorbitol"]
ADDITIVES_DB["E420i"] = ADDITIVES_DICT["e420i"]
ADDITIVES_DB["E322i"] = ADDITIVES_DICT["e322i"]
ADDITIVES_DB["E621"] = ADDITIVES_DICT["glutamato monosodico"]
ADDITIVES_DB["E120"] = ADDITIVES_DICT["carmin"]
ADDITIVES_DB["E133"] = ADDITIVES_DICT["azul brillante"]
ADDITIVES_DB["E338"] = ADDITIVES_DICT["acido fosforico"]
ADDITIVES_DB["E433"] = ADDITIVES_DICT["polisorbato 80"]
ADDITIVES_DB["E466"] = ADDITIVES_DICT["carboximetilcelulosa"]
ADDITIVES_DB["E450"] = ADDITIVES_DICT["difosfatos"]
ADDITIVES_DB["E452"] = ADDITIVES_DICT["difosfatos"]
ADDITIVES_DB["E320"] = ADDITIVES_DICT["bha"]
ADDITIVES_DB["E627"] = {"code": "E627", "safety": "danger", "name": "Guanilato Sódico", "harm": "Potenciador de sabor que aumenta el ácido úrico. Riesgo para personas con gota.", "risk_profile": "🦴 Ácido Úrico / 🧠 Excitotóxico", "adi_warning": "⚠️ Riesgo Gota", "study": "EFSA: Evaluación de nucleótidos y salud metabólica."}
ADDITIVES_DB["E631"] = {"code": "E631", "safety": "danger", "name": "Inosinato Sódico", "harm": "Estimulante del apetito. Altera el umbral de saciedad.", "risk_profile": "⚖️ Metabolismo / 🧠 Neuro", "adi_warning": "⚠️ Evitar en control peso", "study": "JECFA: Evaluación técnica de potenciadores umami."}
ADDITIVES_DB["E150c"] = {"code": "E150c", "safety": "warning", "name": "Caramelo Amónico", "harm": "Colorante industrial. Puede contener trazas de 4-MEI.", "risk_profile": "🧪 Industrial / 🧬 Cáncer (Límite)", "adi_warning": "⚠️ Moderar", "study": "EFSA 2017: Re-evaluación de colorantes caramelo."}
ADDITIVES_DB["E220"] = {"code": "E220", "safety": "danger", "name": "Dióxido de Azufre (Sulfitos)", "harm": "Alérgeno severo. Destruye la vitamina B1 y causa asma.", "risk_profile": "🧪 Alergia / 🛡️ Vitamina B1", "adi_warning": "❌ Muy alérgico", "study": "EFSA: Alerta obligatoria por toxicidad sistémica."}

# Models
class UserAuth(BaseModel): username: str; password: str
class UserSettings(BaseModel): username: str; settings: dict

class RecipeRequest(BaseModel):
    username: Optional[str]
    ingredients: List[str]

class Recipe(BaseModel):
    title: str
    ingredients: List[str]
    steps: List[str]
    nutritional_info: str

class RecipeResponse(BaseModel):
    recipes: List[Recipe]
class Alternative(BaseModel):
    name: str; barcode: str; image_url: Optional[str] = None
    score: int; summary: str; link: str

class AnalysisRequest(BaseModel): username: Optional[str] = None; barcode: str; settings: dict
class VisionRequest(BaseModel): image: str  # Base64 string
class AlternativesRequest(BaseModel): barcode: str; categories: List[str]; product_name: Optional[str] = None

class AnalysisResponse(BaseModel):
    status: str; product_name: str; image_url: Optional[str]
    barcode: Optional[str] = None
    matches: List[str]; ingredients: str; score: int
    nutrients: dict; nutriments: dict; additives: List[dict]
    categories: List[str] = []
    alternatives: List[Alternative] = []

# Routes
@app.get("/daily-tip")
def get_daily_tip():
    HEALTH_TIPS = [
        "🍎 Come una manzana al día para mejorar tu digestión y obtener fibra natural.",
        "💧 Mantente hidratado: beber 2 litros de agua mejora tu energía y concentración.",
        "🥦 Los vegetales de hoja verde son superalimentos ricos en hierro y vitaminas.",
        "🍬 Reduce el azúcar añadido para evitar picos de insulina y cansancio repentino.",
        "🥜 Los frutos secos son snacks ideales, llenos de grasas saludables para el cerebro.",
        "🥑 Un aguacate al día ayuda a proteger tu corazón con grasas monoinsaturadas.",
        "🏃‍♂️ Camina 15 minutos después de comer para ayudar a tu cuerpo a procesar la glucosa.",
        "😴 Dormir bien es vital: 7-8 horas ayudan a controlar las hormonas del hambre.",
        "🧐 Mira los tres primeros ingredientes: son los que más presencia tienen en el producto.",
        "🥖 Cambia el pan blanco por integral para obtener un 50% más de nutrientes y fibra."
    ]
    day_of_year = datetime.now().timetuple().tm_yday
    return {"tip": HEALTH_TIPS[day_of_year % len(HEALTH_TIPS)]}

@app.post("/register")
async def register(user: UserAuth):
    existing = db_get_user(user.username)
    if existing: 
        raise HTTPException(status_code=400, detail="El usuario ya existe")
    
    now = datetime.now().isoformat()
    if supabase:
        supabase.table("users").insert({
            "username": user.username, "password": get_password_hash(user.password),
            "settings": json.dumps({}), "last_active": now
        }).execute()
    else:
        conn = sqlite3.connect(DB_PATH); cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO users (username, password, settings, last_active) VALUES (?, ?, ?, ?)", 
            (user.username, get_password_hash(user.password), json.dumps({}), now)
        )
        conn.commit(); conn.close()
    return {"ok": True}

@app.post("/ia-history-items")
async def get_ia_history_items(request: Dict[str, str]):
    username = request.get("username")
    print(f"DEBUG IA: history request for {username}")
    if not username: return []
    
    if supabase:
        res = supabase.table("history").select("product_name").eq("username", username).order("timestamp", desc=True).execute()
        items = list(dict.fromkeys([r["product_name"] for r in res.data if r.get("product_name")]))
    else:
        conn = sqlite3.connect(DB_PATH); cursor = conn.cursor()
        cursor.execute("SELECT product_name FROM history WHERE username=? ORDER BY timestamp DESC", (username,))
        rows = cursor.fetchall(); conn.close()
        items = list(dict.fromkeys([r[0] for r in rows if r[0]])) 
        
    print(f"DEBUG IA: Found {len(items)} items")
    return items

@app.get("/ia-history-items")
def debug_ia_history():
    return {"status": "Route active", "info": "Use POST with username"}

@app.post("/generate-recipes", response_model=RecipeResponse)
async def generate_recipes(request: RecipeRequest):
    if not GEMINI_API_KEY:
        # Fallback if no API key
        return RecipeResponse(recipes=[
            Recipe(
                title="Sugerencia Premium",
                ingredients=request.ingredients,
                steps=["Configura tu clave de API de Gemini para obtener recetas reales.", "Disfruta de tus ingredientes de forma saludable."],
                nutritional_info="Requiere IA activa."
            )
        ])

    prompt = f"""
    Eres un chef experto en nutrición de FoodGuard Elite. 
    A partir de estos ingredientes: {', '.join(request.ingredients)}
    Genera 3 recetas saludables y detalladas.
    Responde ÚNICAMENTE en formato JSON con la siguiente estructura:
    {{
      "recipes": [
        {{
          "title": "Nombre de la receta",
          "ingredients": ["ingrediente 1", "ingrediente 2"],
          "steps": ["Paso 1", "Paso 2"],
          "nutritional_info": "Resumen nutricional corto"
        }}
      ]
    }}
    """
    
    try:
        # Tried models in order of preference based on list_models() diagnostic
        model_names = ['gemini-2.0-flash', 'gemini-flash-latest', 'gemini-pro-latest']
        model = None
        text = None
        last_err = None
        
        for m_name in model_names:
            try:
                print(f"DEBUG Gemini: Trying model {m_name}...")
                model = genai.GenerativeModel(m_name)
                response = await asyncio.to_thread(model.generate_content, prompt)
                text = response.text
                print(f"DEBUG Gemini: Success with {m_name}")
                break
            except Exception as e:
                print(f"DEBUG Gemini: Fail with {m_name}: {str(e)}")
                last_err = e
                continue
        
        if not text:
            raise last_err or Exception("Todos los modelos de Gemini fallaron")

        print(f"DEBUG Gemini: Response received ({len(text)} bytes)")
        
        # Clean potential markdown from Gemini
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
             text = text.split("```")[1].strip()
        
        data = json.loads(text)
        return RecipeResponse(**data)
    except Exception as e:
        print(f"ERROR Gemini Final Exception: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error IA: {str(e)}")

@app.post("/login")
async def login(user: UserAuth):
    row = db_get_user(user.username)
    if not row or not verify_password(user.password, row.get("password")): 
        raise HTTPException(status_code=401)
    
    db_update_last_active(user.username)
    
    settings = {}
    db_settings = row.get("settings")
    if db_settings:
        try:
            settings = json.loads(db_settings) if isinstance(db_settings, str) else db_settings
        except:
            pass
            
    return {"username": user.username, "settings": settings}

@app.post("/ping")
async def ping(request: Dict[str, str]):
    username = request.get("username")
    if not username: return {"status": "ignored"}
    db_update_last_active(username)
    return {"status": "ok"}

@app.post("/save-settings")
async def save_settings(data: UserSettings):
    print(f"DEBUG: Saving settings for user {data.username}: {data.settings}")
    if supabase:
        supabase.table("users").update({"settings": json.dumps(data.settings)}).eq("username", data.username).execute()
    else:
        conn = sqlite3.connect(DB_PATH); cursor = conn.cursor()
        cursor.execute("UPDATE users SET settings=? WHERE username=?", (json.dumps(data.settings), data.username))
        conn.commit(); conn.close()
    return {"ok": True}

@app.get("/history/{username}")
async def get_history(username: str):
    history = db_get_history(username, limit=20)
    # Uniform format for Frontend
    return [{
        "barcode": h.get("barcode"), 
        "name": h.get("product_name") or h.get("name"), 
        "status": h.get("status"), 
        "score": h.get("score"), 
        "date": h.get("timestamp") or h.get("date")
    } for h in history]

@app.post("/analyze-ingredients-image")
async def analyze_ingredients_image(request: VisionRequest):
    """Identify food ingredients from a camera photo using Gemini Vision"""
    try:
        # Clean base64 data
        img_data = request.image
        if "," in img_data:
            img_data = img_data.split(",")[1]
        
        image_bytes = base64.b64decode(img_data)
        
        # Absolute priority list: 2.0-flash -> 1.5-flash -> 1.5-flash-8b -> 1.5-pro (last resort)
        models_to_try = ['gemini-2.0-flash', 'gemini-1.5-flash', 'gemini-1.5-flash-8b', 'gemini-1.5-pro']
        prompt = "Identifica todos los ingredientes o alimentos individuales que ves en esta imagen. Devuelve SOLO una lista de nombres de alimentos separados por comas, sin explicaciones ni introducciones. Ejemplo: Tomate, Cebolla, Pollo, Arroz."
        
        last_error = ""
        for model_name in models_to_try:
            for attempt in range(2): # Double attempt per model
                try:
                    print(f"DEBUG Vision: Trying {model_name} (Attempt {attempt+1})")
                    model = genai.GenerativeModel(model_name)
                    response = await asyncio.to_thread(
                        model.generate_content,
                        [prompt, {'mime_type': 'image/jpeg', 'data': image_bytes}]
                    )
                    text = response.text.strip()
                    if text:
                        ingredients = [i.strip() for i in text.split(",") if i.strip()]
                        return {"ingredients": ingredients, "model": model_name}
                except Exception as e:
                    last_error = str(e)
                    print(f"WARNING Vision: {model_name} failed: {last_error}")
                    if "429" in last_error or "Quota" in last_error:
                        await asyncio.sleep(2) # Give it a breath
                    continue
        
        # If absolutely everything fails, let's not return a 500. 
        # Return an empty list so the UI can handle it gracefully.
        return {"ingredients": [], "error": "Quota Exceeded", "fallback": True}
        
    except Exception as e:
        print(f"ERROR Vision overall: {str(e)}")
        return {"ingredients": [], "error": str(e)}

async def get_healthier_alternatives(categories_tags, current_barcode, original_name=None):
    """Find products in the same category with better Nutri-Score, ensuring relevance"""
    print(f"DEBUG ALTS: Searching for alternatives. Product: {original_name}, Categories: {categories_tags}")
    
    if not categories_tags: 
        return []

    # Filter out extremely broad categories that cause irrelevant results (like Mayo -> Tomato Sauce)
    BROAD_CATEGORIES = {
        "en:sauces", "en:snacks", "en:beverages", "en:meals", "en:groceries", 
        "en:dairy", "en:meats", "en:plant-based-foods-and-beverages", "en:desserts",
        "en:sweet-snacks", "en:salty-snacks", "en:biscuits-and-cakes", "en:confectioneries"
    }

    # Extract keywords from original name for relevance check
    keywords = []
    if original_name:
        # Simple extraction: words > 3 chars
        keywords = [w.lower() for w in re.findall(r'\w{4,}', original_name) if w.lower() not in ["para", "con", "de", "del"]]
    
    # Try categories from most specific to least specific
    cats_to_try = categories_tags[::-1] # Reverse original list
    
    for cat in cats_to_try:
        # If the category is too broad and we have other options, skip it to avoid "Mayo -> Tomato"
        if cat in BROAD_CATEGORIES and len(cats_to_try) > 1 and cat != cats_to_try[0]:
            print(f"DEBUG ALTS: Skipping broad category {cat} as fallback.")
            continue

        url = f"https://world.openfoodfacts.org/cgi/search.pl?action=process&tagtype_0=categories&tag_contains_0=contains&tag_0={cat}&tagtype_1=nutrition_grades&tag_contains_1=contains&tag_1=A&json=true&page_size=30&sort_by=unique_scans_n"
        headers = {"User-Agent": "FoodGuard/1.0 (aleco121@example.com) - Python/httpx"}
        
        try:
            print(f"DEBUG ALTS: Trying category {cat}...")
            async with httpx.AsyncClient(timeout=10.0) as client:
                # Try A, then B
                data = None
                grades_to_try = ['A', 'B']
                # If we are in the most specific category, we can also try C if A/B fail
                if cat == cats_to_try[0]:
                    grades_to_try.append('C')

                for grade in grades_to_try:
                    current_url = url.replace("tag_1=A", f"tag_1={grade}")
                    r = await client.get(current_url, headers=headers)
                    if r.status_code != 200: continue
                    resp_data = r.json()
                    if resp_data.get("products"):
                        data = resp_data
                        break
                
                if not data or not data.get("products"):
                    print(f"DEBUG ALTS: No suitable products found in {cat} for grades {grades_to_try}")
                    continue

                products = data.get("products", [])
                alts = []
                for p in products:
                    if p.get("code") == current_barcode: continue
                    
                    p_name = p.get("product_name", p.get("product_name_es", "Desconocido"))
                    if not p_name or p_name == "Desconocido": continue

                    # HIGHLIGHT: Relevance Check
                    # If we are in a potentially broad category, check if name matches keywords
                    if keywords:
                        name_lower = p_name.lower()
                        match_found = any(k in name_lower for k in keywords)
                        # If a specific category fails and we are at a broader level, 
                        # we require at least one keyword match to prevent "Mayo -> Tomato"
                        if not match_found and cat in BROAD_CATEGORIES:
                            continue

                    grade = (p.get("nutrition_grades") or "B").upper()
                    img = p.get("image_front_url") or p.get("image_url")
                    
                    alts.append(Alternative(
                        name=p_name,
                        barcode=p.get("code", ""),
                        image_url=img,
                        score=95 if grade == 'A' else 80 if grade == 'B' else 60,
                        summary=f"Puntuación Nutricional {grade}. Opción más saludable y relacionada en su categoría.",
                        link=f"https://es.openfoodfacts.org/producto/{p.get('code')}"
                    ))
                    if len(alts) >= 3: break
                
                if alts:
                    print(f"DEBUG ALTS: Successfully found {len(alts)} relevant alternatives in {cat}")
                    return alts
        except Exception as e:
            print(f"DEBUG ALTS: Exception for {cat}: {str(e)}")
            traceback.print_exc()
            
    print("DEBUG ALTS: Finished searching all categories with 0 results.")
    return []

# Analysis Core
@app.post("/analyze", response_model=AnalysisResponse)
async def analyze_product(request: AnalysisRequest):
    url = f"https://world.openfoodfacts.org/api/v0/product/{request.barcode}.json"
    headers = {"User-Agent": "FoodGuard/1.0 (aleco121@example.com) - Python/httpx"}
    
    data = None
    async with httpx.AsyncClient(timeout=15.0) as client:
        for attempt in range(3): # Try up to 3 times
            try:
                print(f"DEBUG: Attempting analysis for barcode {request.barcode} (Attempt {attempt+1})")
                response = await client.get(url, headers=headers)
                if response.status_code == 200:
                    data = response.json()
                    break
            except Exception as e:
                print(f"DEBUG: Request failed: {str(e)}")
                if attempt == 2: raise HTTPException(status_code=504, detail="Error de conexión con el servidor de alimentos")
                await asyncio.sleep(1) # Wait before retry

        if not data or data.get("status") == 0:
            return AnalysisResponse(status="ERROR", product_name="No encontrado", image_url=None, matches=[], ingredients="", score=0, nutrients={}, nutriments={}, additives=[])
        
        product = data.get("product", {}) # Renamed to p_data in instruction, but keeping original for consistency with existing code
        print(f"DEBUG: Processing product: {product.get('product_name', 'Unknown')}")
        print(f"DEBUG: Raw Additives Tags: {product.get('additives_tags', [])}")
        print(f"DEBUG: Raw Ingredients Text: {product.get('ingredients_text', 'NOT FOUND')}")

        product_name = product.get("product_name", product.get("product_name_es", "Desconocido"))
        image_url = product.get("image_front_url")
        
        # Try multiple keys for ingredients
        ingredients_text = product.get("ingredients_text_es") or product.get("ingredients_text") or product.get("ingredients_text_en") or ""
        ingredients_text = ingredients_text.lower()
        
        # 2. Scoring Logic (Simulated Nutri-Score 0-100)
        # Based on energy, sugars, salt, saturated fat + bonus for fiber/protein
        score = 80 # Initial base
        nutriments = product.get("nutriments", {})
        levels = product.get("nutrient_levels", {})
        sugars = nutriments.get("sugars_100g", 0)
        salt = nutriments.get("salt_100g", 0)
        fat = nutriments.get("fat_100g", 0)
        fiber = nutriments.get("fiber_100g", 0)
        protein = nutriments.get("proteins_100g", 0)
        
        # Penalties
        if sugars > 12: score -= 20
        if salt > 1.2: score -= 20
        if fat > 18: score -= 15
        
        # Positive Rewards
        if sugars < 2 and salt < 0.4: score += 10
        if fiber > 5: score += 5
        if protein > 10: score += 5
        
        # Update levels for frontend grid
        levels["fiber"] = "high" if fiber > 4 else "low"
        levels["proteins"] = "high" if protein > 10 else "low"

        # 3. Additives (Super-Aggressive Detection System)
        found_additives = []
        found_codes = set()
        
        tags = product.get("additives_tags", [])
        for tag in tags:
            code = tag.split(":")[-1].upper()
            if code not in found_codes:
                detail = ADDITIVES_DB.get(code) or get_fallback_detail(code)
                found_additives.append({"code": code, **detail})
                found_codes.add(code)

        # Priority 2: Full-Name and Synonym Matching (Crucial for Spanish market)
        if ingredients_text:
            text_clean = ingredients_text.lower()
            for name_key, info in ADDITIVES_DICT.items():
                code = info["code"]
                if code not in found_codes:
                    if name_key in text_clean:
                        found_additives.append(info)
                        found_codes.add(code)
            
            # Priority 3: Regex Fallback for E-Codes (E123, E-123, e 123)
            extra_codes = re.findall(r'[eE][-\s]?(\d{3,4}[a-z]?)', text_clean)
            for num in extra_codes:
                code_raw = num.upper()
                code = f"E{code_raw}"
                if code not in found_codes:
                    detail = ADDITIVES_DB.get(code) or ADDITIVES_DB.get(f"E-{code_raw}")
                    if not detail: detail = get_fallback_detail(code)
                    found_additives.append({"code": code, **detail})
                    found_codes.add(code)

        # 3.1 ADDITIVE PENALTIES (Stricter Yuka-Plus Logic)
        additive_penalty = 0
        has_danger = False
        has_warning = False
        
        # Super-aggressive Aroma detection
        text_clean = ingredients_text.lower()
        if "aroma" in text_clean or "aromatizante" in text_clean:
            if "AROMA" not in found_codes:
                aroma_info = ADDITIVES_DICT.get("aroma")
                found_additives.append({"code": "AROMA", **aroma_info})
                found_codes.add("AROMA")

        for a in found_additives:
            if a["safety"] == "danger":
                additive_penalty += 40 
                has_danger = True
            elif a["safety"] == "warning":
                additive_penalty += 20 
                has_warning = True
        
        score -= additive_penalty
        if has_danger: score = min(score, 44) 
        elif has_warning: score = min(score, 74) 
        if score < 5: score = 5
        if score > 100: score = 100

        # 4. Filters Match (Improved Robustness)
        RISK_DICTS = {
            "gluten": ["trigo", "cebada", "centeno", "avena", "espelta", "malta", "gluten"],
            "lactose": ["leche", "suero", "caseina", "nata", "mantequilla", "queso", "lactosa", "lácteos"],
            "sugar": ["azúcar", "jarabe", "dextrosa", "fructosa", "melaza", "sacarosa"],
            "nuts": ["cacahuete", "almendra", "avellana", "nuez", "anacardo", "pistacho", "frutos de cáscara"],
            "palm_oil": ["palma", "palmiste"],
            "vegetarian": ["carne", "pollo", "cerdo", "ternera", "pescado", "marisco", "gelatina", "grasas animales"],
            "vegan": ["carne", "pollo", "cerdo", "ternera", "pescado", "marisco", "gelatina", "huevo", "leche", "miel", "queso", "mantequilla"],
            "msg": ["glutamato", "e621", "e-621", "msg", "monosodium glutamate", "potenciador del sabor"]
        }
        
        found_matches = []
        if ingredients_text:
            for key, items in RISK_DICTS.items():
                is_active = (
                    request.settings.get(f"{key}_free") or 
                    request.settings.get(f"no_{key}") or 
                    request.settings.get(f"low_{key}") or 
                    request.settings.get(key)
                )
                
                if is_active:
                    for item in items:
                        if item in ingredients_text:
                            if key == "gluten" and "trigo sarraceno" in ingredients_text and item == "trigo": continue
                            # Improved description
                            label = {
                                "gluten": "Gluten", "lactose": "Lactosa", "sugar": "Azúcar",
                                "nuts": "Frutos Secos", "palm_oil": "Aceite de Palma",
                                "vegetarian": "No Vegetariano", "vegan": "No Vegano", "msg": "Glutamato"
                            }.get(key, key.capitalize())
                            found_matches.append(f"{label}: Detectado '{item}'")
                            break
                    
                    if key == "msg" and "E621" in found_codes and not any("MSG" in m for m in found_matches):
                        found_matches.append("MSG: Detectado Aditivo E621")
                    elif key == "lactose" and any(c in found_codes for c in ["E966"]) and not any("Lactosa" in m for m in found_matches):
                        found_matches.append("Lactosa: Detectado Aditivo E966")

        # Nutrient-based Alerts (Numerical)
        if request.settings.get("low_fat") or request.settings.get("no_fat"):
            fat_val = nutriments.get("fat_100g", 0)
            if fat_val > 17.5: # Standard high fat threshold
                found_matches.append(f"Grasas: Nivel muy alto ({fat_val}g/100g)")
        
        if request.settings.get("low_sugar") and not any("Azúcar" in m for m in found_matches):
            sugar_val = nutriments.get("sugars_100g", 0)
            if sugar_val > 22.5: # Standard high sugar threshold
                found_matches.append(f"Azúcar: Nivel muy alto ({sugar_val}g/100g)")
        
        status_res = "WARNING" if found_matches or score < 40 else "SAFE"
        
        if request.username:
            print(f"DEBUG: Inserting history for user {request.username}, product {product_name}")
            db_save_history(request.username, request.barcode, product_name, status_res, score)

        # 5. Return basic data (Alternatives will be lazy-loaded)
        categories = product.get("categories_tags", [])
        
        return AnalysisResponse(
            status=status_res, product_name=product_name, image_url=image_url,
            barcode=request.barcode,
            matches=found_matches, ingredients=ingredients_text or "No disponible.",
            score=int(score), nutrients=levels, nutriments=nutriments, additives=found_additives,
            categories=categories,
            alternatives=[]
        )

@app.post("/alternatives", response_model=List[Alternative])
async def get_alternatives_endpoint(request: AlternativesRequest):
    print(f"DEBUG: Lazy loading alternatives for {request.barcode} ({request.product_name})")
    return await get_healthier_alternatives(request.categories, request.barcode, request.product_name)
        
def get_fallback_detail(code):
    """Deep Clinical Fallback for missing E-codes based on institutional risk ranges with detailed contexts."""
    code = code.upper()
    try:
        match = re.search(r'\d+', code)
        if not match: raise ValueError
        num = int(match.group())
    except:
        return {"name": f"Aditivo {code}", "safety": "warning", "harm": "Sin datos específicos. Categoría bajo vigilancia clínica.", "harm_detail": "No se dispone de un informe clínico individual para este compuesto específico. Se recomienda precaución ante la falta de transparencia en su evaluación de seguridad a largo plazo.", "risk_profile": "🧪 Desconocido", "adi_warning": "⚠️ Consultar DDA", "study": "EFSA: En ciclo de re-evaluación.", "study_detail": "El aditivo se encuentra en la lista de sustancias pendientes de actualización técnica por parte de los paneles de seguridad alimentaria."}
    
    if 100 <= num <= 199:
        return {
            "name": f"Colorante {code}", "safety": "danger", 
            "harm": "Colorante industrial. Riesgo de hiperactividad y reacciones alérgicas.", 
            "harm_detail": "Los colorantes de este rango suelen ser azoicos o sintéticos, conocidos por inducir la liberación de histamina y alterar la barrera mucosa en niños sensibles. Pueden interferir con los neurotransmisores cerebrales.",
            "risk_profile": "🧬 Alergénico / 🧠 Neuroconductual", "adi_warning": "⚠️ Evitar en niños", 
            "study": "EFSA / Univ. Southampton: Asociación con trastornos de conducta infantil.",
            "study_detail": "Múltiples metaanálisis confirman que la eliminación de colorantes artificiales mejora los síntomas de TDAH en un subgrupos significativo de la población infantil."
        }
    elif 200 <= num <= 299:
        return {
            "name": f"Conservante {code}", "safety": "danger", 
            "harm": "Protección química contra microbios. Potencial daño al material genético celular.", 
            "harm_detail": "Sustancias diseñadas para inhibir la vida microbiana que, en dosis acumulativas, pueden inducir estrés oxidativo y genotoxicidad en las células gástricas humanas.",
            "risk_profile": "🧬 Genotoxicidad / 🧪 Químico", "adi_warning": "❌ Ingesta limitada", 
            "study": "ANSES: Los conservantes químicos deben ser minimizados por su impacto acumulativo.",
            "study_detail": "Informes institucionales alertan sobre el 'efecto cóctel': la interacción de varios conservantes en una misma dieta puede multiplicar su toxicidad individual."
        }
    elif 300 <= num <= 399:
        if num > 337:
             return {
                 "name": f"Antioxidante/Fosfato {code}", "safety": "danger", 
                 "harm": "Fosfatos industriales. Elevan el riesgo de daño cardiovascular y calcificación renal.", 
                 "harm_detail": "El fósforo inorgánico se absorbe al 100%, elevando los niveles de la hormona FGF23, lo que daña las arterias y sobrecarga los riñones de forma crónica.",
                 "risk_profile": "🫀 Vascular / 🚿 Renal", "adi_warning": "⚠️ Muy acumulativo", 
                 "study": "BMJ (INSERM): Los fosfatos añadidos superan la DDA recomendada en UPFs.",
                 "study_detail": "Estudios epidemiológicos vinculan el consumo elevado de fosfatos con una menor esperanza de vida debido a la calcificación vascular prematura."
             }
        return {"name": f"Antioxidante {code}", "safety": "safe", "harm": "Regulador de acidez o protección contra oxidación.", "harm_detail": "Antioxidantes generalmente derivados de fuentes naturales que ayudan a prevenir el enranciamiento sin efectos adversos conocidos en dosis estándar.", "risk_profile": "✅ Probable Seguro", "adi_warning": "✅ Seguro en dosis normales", "study": "EFSA: Evaluación tecnológica general.", "study_detail": "Evaluación favorable basada en la ausencia de bioacumulación y toxicidad aguda."}
    elif 400 <= num <= 499:
        return {
            "name": f"Emulgente/Espesante {code}", "safety": "warning", 
            "harm": "Agente de textura industrial. Altera la barrera de mucina y la microbiota intestinal.", 
            "harm_detail": "Actúan como detergentes en el intestino, disolviendo la capa de moco que protege el epitelio y facilitando la traslocación bacteriana y la inflamación crónica.",
            "risk_profile": "🦠 Microbiota / 🩹 Barrera Intestinal", "adi_warning": "⚠️ Marcador Ultraprocesado", 
            "study": "Nature Immunology: Impacto en la inflamación intestinal crónica por detergentes alimentarios.",
            "study_detail": "Se ha demostrado en modelos in vitro y animales que estos aditivos promueven la disbiosis y aumentan la susceptibilidad a enfermedades autoinmunes."
        }
    elif 600 <= num <= 699:
        return {
            "name": f"Potenciador {code}", "safety": "danger", 
            "harm": "Excitotoxina química. Estimula artificialmente el apetito y puede causar migrañas.", 
            "harm_detail": "Compuestos que sobreestimulan las papilas gustativas y los receptores neuronales, provocando una respuesta de placer artificial que anula las señales naturales de saciedad.",
            "risk_profile": "🧠 Neurosensible / 🧪 Excitotóxico", "adi_warning": "⚠️ Evitar sensibilidad", 
            "study": "JECFA: Evaluación sobre neuroexcitación y glutamatos.",
            "study_detail": "La evidencia sugiere que personas con sensibilidad química pueden experimentar el 'síndrome del restaurante chino' incluso con dosis moderadas de estos potenciadores."
        }
    
    return {"name": f"Aditivo {code}", "safety": "warning", "harm": "Aditivo industrial multifuncional. Consumo debe ser limitado.", "harm_detail": "Sustancia de uso industrial extendido para mejorar la palatabilidad o conservación. Se recomienda priorizar alimentos frescos sin estos marcadores de ultraprocesamiento.", "risk_profile": "🧪 Industrial", "adi_warning": "⚠️ Consultar DDA", "study": "EFSA: Bajo revisión técnica.", "study_detail": "Categorizado como ingrediente cosmético alimentario pendiente de estudios epidemiológicos a largo plazo."}

@app.get("/stats/{username}")
async def get_stats(username: str):
    if supabase:
        res = supabase.table("history").select("score, status").eq("username", username).execute()
        rows = [(r["score"], r["status"]) for r in res.data]
    else:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT score, status FROM history WHERE username=?", (username,))
        rows = cursor.fetchall()
        conn.close()
    
    if not rows:
        return {"total": 0, "avg": 0, "safe": 0, "warning": 0, "danger": 0}
    
    total = len(rows)
    avg = sum(r[0] for r in rows) / total
    safe = sum(1 for r in rows if r[1] == 'SAFE')
    warning = sum(1 for r in rows if r[1] == 'WARNING')
    danger = sum(1 for r in rows if r[1] == 'DANGER')
    
    return {"total": total, "avg": int(avg), "safe": safe, "warning": warning, "danger": danger}

@app.post("/lookup-additive")
async def lookup_additive(request: dict):
    q = request.get("query", "").lower().strip()
    if not q: return {"error": "Query vacía"}
    
    # Check by code
    code = q if q.startswith("e") else f"e{q}"
    code_upper = code.upper()
    detail = ADDITIVES_DB.get(code_upper) or ADDITIVES_DB.get(f"E-{q.upper()}")
    
    # Check by name in DICT if not found by code
    if not detail:
        for k, v in ADDITIVES_DICT.items():
            if q in k or q in v["name"].lower():
                detail = v
                break
                
    if not detail and re.search(r'\d+', q):
        detail = get_fallback_detail(code_upper)
        
    if not detail:
        return {"error": "Aditivo no encontrado"}
    return detail


app.mount("/static", StaticFiles(directory="static"), name="static")

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
