import streamlit as st
import pdfplumber
import google.generativeai as genai
import requests
import io
import re
import json
import pandas as pd
import altair as alt
import time

# --- CONFIGURACIÓN GENERAL ---
st.set_page_config(page_title="Screenplay Analyst", layout="wide")


# login_screen() - Función para manejar autenticación simple sin backend

def login_screen():
    try:
        # Esto busca la sección [passwords] en la configuración de la nube
        USUARIOS_PERMITIDOS = st.secrets["passwords"]
    except FileNotFoundError:
        # Si te olvidaste de configurar los secrets, da un error claro
        st.error("Error: No se han configurado los usuarios en los Secrets.")
        st.stop()
    
    if 'logged_in' not in st.session_state:
        st.session_state.logged_in = False

    if not st.session_state.logged_in:
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            st.markdown("## 🔒 Restricted access")
            st.info("This tool is private. Please enter your credentials.")
            
            username = st.text_input("User")
            password = st.text_input("Password", type="password")
            
            if st.button("Login", type="primary"):
                if username in USUARIOS_PERMITIDOS and USUARIOS_PERMITIDOS[username] == password:
                    st.session_state.logged_in = True
                    st.success("¡Access granted!")
                    st.rerun()
                else:
                    st.error("Incorrect user or password")
        st.stop()

login_screen()

with st.sidebar:
    if st.button("🔒 Log out"):
        st.session_state.logged_in = False
        st.rerun()


# La app comienza aquí, después de la autenticación. Todo el código relacionado con la lógica de análisis y UI va debajo de esta línea.
# 1. API KEY
API_KEY = st.secrets["GOOGLE_API_KEY"] 
genai.configure(api_key=API_KEY)

# 2. URL FIJA DE SICA
SICA_URL = "https://www.sicacine.org.ar/docs/Salarios%20Largometrajes%20Nacionales%20Febrero%2026.pdf"

# --- FUNCIONES ---

def extract_text_from_bytes(file_bytes):
    try:
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            text = "".join([page.extract_text() or "" for page in pdf.pages])
            return text
    except Exception as e:
        return f"Error leyendo PDF: {e}"

def fetch_sica_data():
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(SICA_URL, headers=headers, timeout=10)
        return extract_text_from_bytes(response.content) if response.status_code == 200 else None
    except:
        return None

def retry_request(model, prompt, retries=3):
    for attempt in range(retries):
        try:
            return model.generate_content(prompt)
        except Exception as e:
            if "429" in str(e):
                st.toast(f"⏳ High traffic. Waiting 60s... ({attempt+1}/{retries})", icon="⚠️")
                time.sleep(60)
                continue
            raise e
    raise Exception("Too many API request. Try again later.")

def generate_analysis(script_text, sica_text, exchange_rate, include_narrative, include_production, include_diversity):
    model = genai.GenerativeModel('gemini-2.5-flash')

    # --- ESTRUCTURA DE PROMPT REFORZADA ---
    prompt = f"""
    Actúa como Productor Ejecutivo y Analista de Datos.
    Analiza el guion adjunto.
    
    INSTRUCCIÓN DE FORMATO:
    - NO escribas introducciones ni saludos.
    - Empieza INMEDIATAMENTE con el primer título Markdown.
    - Genera TODAS las secciones solicitadas sin omitir ninguna.
    
    CONTEXTO: 1 USD = ${exchange_rate} ARS.
    Datos SICA: {sica_text[:5000] if sica_text else "N/A"}...
    GUION: {script_text[:350000]} 
    
    ESTRUCTURA OBLIGATORIA DEL REPORTE (Sigue este orden):
    """

    if include_narrative:
        prompt += """
        \n--------------------------------------------------
        SECCIÓN 1: ANÁLISIS NARRATIVO (Obligatorio)
        --------------------------------------------------
        Formato Markdown:
        ### 1. ANÁLISIS NARRATIVO
        * Logline, Sinopsis.
        * **Crítica (1-10):** Evaluación de originalidad, estructura, personajes y diálogos.
        * **Referencias:** 5 películas similares.

        AL FINAL DE ESTA SECCIÓN, inserta estos DOS bloques JSON ocultos (usa bloques de código ```json ... ```):
        
        JSON 1 (Temas): [{"Personaje": "A", "Tema": "X", "Porcentaje": 50}...]
        JSON 2 (Evolución): 
        [
          {"Momento": "1. Setup", "Alegría": 80, "Tristeza": 10, "Ira": 5, "Miedo": 5, "Tensión": 10},
          ... hasta el momento 8
        ]
        """

    if include_production:
        prompt += """
        \n--------------------------------------------------
        SECCIÓN 2: PRODUCCIÓN (Obligatorio)
        --------------------------------------------------
        Formato Markdown:
        ### 2. PRODUCCIÓN
        * **Casting Ideal:** Sugiere actores (preferiblemente mercado Latam/Argentina) para los roles principales.
        * **Desglose de Locaciones:** Lista las locaciones principales necesarias, describiendo su estética (Look & Feel) y complejidad logística (INT/EXT, Día/Noche).
        * **SI O SI Genera una Tabla de Presupuesto en USD (Pre, Rodaje, Post). Tiene que ser en formato tabla obligatoriamente. El presupuesto tiene que ser moderado. NO EXAGERADO, NO MUY BAJO. Tiene que ser estándar, considerando una producción mediana. También tiene que ser consistente con todas las consultas. No puede ser un presupuesto muy distinto en consultas distintas.**
        * **Plan de financiamiento potencial.**
        """

    if include_diversity:
        prompt += """
        \n--------------------------------------------------
        SECCIÓN 3: DIVERSIDAD (Obligatorio)
        --------------------------------------------------
        Formato Markdown:
        ### 3. DIVERSIDAD
        Analiza Test Bechdel y Estereotipos.
        TAREA DE CÁLCULO:
        Analiza los personajes que hablan en el guion.
        Estima el porcentaje REAL de líneas de diálogo dichas por Hombres, Mujeres y Disidencias en ESTE guion específico. No inventes datos genéricos.
        
        AL FINAL, inserta el JSON con tus cálculos (debe sumar 100%):
        ```json 
        { "Hombres": XX, "Mujeres": XX, "Disidencias": XX } 
        ```
        """

    with st.spinner('Analizando guion completo (Esto puede tomar unos segundos)...'):
        response = retry_request(model, prompt)
        return response.text

# --- INTERFAZ ---
with st.sidebar:
    st.header("📂 1. Load script")
    uploaded_file = st.file_uploader("Load the PDF", type="pdf")
    st.divider()
    st.header("⚙️ 2. Configuration")
    check_narrativo = st.checkbox("Narrative Analysis", value=True)
    check_produccion = st.checkbox("Production Analysis", value=True)
    check_diversity = st.checkbox("D&I Analysis", value=False)
    if check_produccion:
        dolar_cotizacion = st.number_input("USD value", value=1250)

st.title("🎬 Screenplay Analyst")

if uploaded_file is not None:
    try:
        with pdfplumber.open(uploaded_file) as pdf:
            script_text = "".join([page.extract_text() or "" for page in pdf.pages])
    except: st.error("Error PDF"); st.stop()

    if st.button("🚀 Create report", type="primary"):
        
        # --- FIX BUG 1: Validar selección ---
        if not (check_narrativo or check_produccion or check_diversity):
            st.error("⚠️ Selected at least one option to begin.")
            st.stop()
            
        sica_data = fetch_sica_data() if check_produccion else ""
        
        try:
            full_response = generate_analysis(
                script_text, sica_data, dolar_cotizacion if check_produccion else 0,
                check_narrativo, check_produccion, check_diversity
            )
            
            # --- PROCESAMIENTO ---
            json_matches = re.findall(r'```json\n(.*?)\n```', full_response, re.DOTALL)
            topics_data, arc_data, diversity_data = None, None, None
            
            for json_str in json_matches:
                try:
                    data = json.loads(json_str)
                    if isinstance(data, list) and len(data) > 0:
                        if "Tema" in data[0]: topics_data = data
                        elif "Alegría" in data[0] or "Tensión" in data[0]: arc_data = data
                    elif isinstance(data, dict): diversity_data = data
                except: continue
            
            text_display = re.sub(r'```json\n(.*?)\n```', '', full_response, flags=re.DOTALL)
            
            # MOSTRAR TEXTO
            st.markdown(text_display)
            
            # --- GRÁFICOS ---
            if check_narrativo and topics_data:
                st.divider()
                st.subheader("🗣️ ADN Temático")
                chart = alt.Chart(pd.DataFrame(topics_data)).mark_bar().encode(
                    x=alt.X('Personaje', sort=None), y='Porcentaje', color=alt.Color('Tema', scale=alt.Scale(scheme='tableau20')),
                    tooltip=['Personaje','Tema', 'Porcentaje']
                ).properties(height=400)
                st.altair_chart(chart, use_container_width=True)

            if check_narrativo and arc_data:
                st.divider()
                st.subheader("📈 Evolución emocional de la historia")
                st.caption("Evolución de 5 emociones clave a lo largo de la trama.")
                
                df_long = pd.DataFrame(arc_data).melt('Momento', var_name='Emoción', value_name='Intensidad')
                domain = ['Alegría', 'Tristeza', 'Ira', 'Miedo', 'Tensión']
                range_ = ['#FFD700', '#1f77b4', '#d62728', '#8A2BE2', '#000000'] 
                
                chart_arc = alt.Chart(df_long).mark_line(point=True, strokeWidth=3).encode(
                    x=alt.X('Momento', sort=None, title='Progresión'), 
                    y='Intensidad',
                    color=alt.Color('Emoción', scale=alt.Scale(domain=domain, range=range_)),
                    tooltip=['Momento', 'Emoción', 'Intensidad']
                ).properties(height=500).interactive()
                st.altair_chart(chart_arc, use_container_width=True)

            if check_diversity and diversity_data:
                st.divider()
                st.subheader("📊 Participación por Género")
                st.bar_chart(diversity_data, color="#FF4B4B")

        except Exception as e:
            st.error(f"Error: {e}")
else:
    st.info("👉 upload your script to begin.")
    st.markdown("""
    **Welcome to Screenplay Analyst.**
    *Narrative analysis + production analysis + D&I analysis.*

    """)










