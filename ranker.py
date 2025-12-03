import streamlit as st
import pandas as pd
import pdfplumber
import docx
from openai import OpenAI
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
import io
import json
import zipfile
import os

# --- CONFIGURATION ---
OPENAI_API_KEY = st.secrets["OPENAI_API_KEY"]
GMAIL_USER = st.secrets["GMAIL_USER"]
GMAIL_APP_PASSWORD = st.secrets["GMAIL_APP_PASSWORD"]

client = OpenAI(api_key=OPENAI_API_KEY)

# --- HELPER: FILE PROCESSING ---

def read_file_content(file_obj, filename):
    """
    Reads text from a file-like object based on extension.
    """
    text = ""
    filename = filename.lower()
    
    try:
        if filename.endswith(".pdf"):
            with pdfplumber.open(file_obj) as pdf:
                for page in pdf.pages:
                    t = page.extract_text()
                    if t: text += t + "\n"
                    
        elif filename.endswith(".docx"):
            doc = docx.Document(file_obj)
            for para in doc.paragraphs:
                text += para.text + "\n"
                
        elif filename.endswith(".txt"):
            text = str(file_obj.read(), "utf-8", errors='ignore')
            
    except Exception as e:
        return f"Error reading {filename}: {e}"
        
    return text[:4000] # Limit tokens

def process_uploaded_files(uploaded_files):
    """
    Handles individual files AND unzips .zip archives in memory.
    Returns a list of dictionaries: [{'name': 'john.pdf', 'text': '...'}, ...]
    """
    processed_docs = []
    
    for uploaded_file in uploaded_files:
        # 1. Handle ZIP Files
        if uploaded_file.name.lower().endswith(".zip"):
            try:
                with zipfile.ZipFile(uploaded_file) as z:
                    for filename in z.namelist():
                        # Skip Mac OS hidden files and directories
                        if "__MACOSX" in filename or filename.endswith("/"): continue
                        
                        # Only process supported extensions inside the zip
                        if filename.lower().endswith(('.pdf', '.docx', '.txt')):
                            with z.open(filename) as f:
                                # We need to copy bytes to BytesIO so libraries can read it multiple times if needed
                                file_content = io.BytesIO(f.read())
                                text = read_file_content(file_content, filename)
                                processed_docs.append({"name": filename, "text": text})
            except Exception as e:
                st.error(f"Error unzipping {uploaded_file.name}: {e}")
                
        # 2. Handle Individual Files
        else:
            text = read_file_content(uploaded_file, uploaded_file.name)
            processed_docs.append({"name": uploaded_file.name, "text": text})
            
    return processed_docs

# --- AI ANALYSIS ---
def analyze_candidate(candidate_text, jd_text, filename):
    prompt = f"""
    You are a Forensic Technical Recruiter. Analyze this candidate.
    
    JOB DESCRIPTION:
    {jd_text[:2000]}
    
    CANDIDATE CV:
    {candidate_text[:3000]}
    
    TASK:
    1. Score (0-100): Strict match against JD.
    2. Summary: 2 sentences.
    3. Red Flags: Gaps, hopping, or missing required skills.
    
    4. INTERROGATION KIT (The "Truth Test"):
       - Find 3 SPECIFIC claims in the CV (e.g. "Managed $5M budget", "Used AWS Lambda", "Tenure 2018-2022").
       - Turn them into Closed Questions to verify the fact.
       - Q1/A1: "What was the specific budget?" -> Ans: "$5M" (From CV).
       - Q2/A2: "Which specific AWS service did you use for X?" -> Ans: "Lambda" (From CV).
       - Q3/A3: "Verify exact dates at [Company]." -> Ans: "2018-2022" (From CV).
       *IMPORTANT: The 'Answer' MUST be explicitly found in the text.*
    
    5. Behavioral Q (Open): One question to probe a weakness or gap.
    
    6. MANAGER BLURB: 1-sentence sales pitch for Slack.
    7. OUTREACH EMAIL: Personalized email referencing a specific detail.
    8. BLIND PROFILE: Summary with NO Name/Gender/School.
    
    OUTPUT JSON KEYS: 
    "score", "summary", "pros", "cons", 
    "q1", "a1", "q2", "a2", "q3", "a3", "open_q", 
    "manager_blurb", "outreach_email", "blind_summary"
    """
    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            response_format={"type": "json_object"},
            messages=[{"role": "user", "content": prompt}]
        )
        return json.loads(response.choices[0].message.content)
    except Exception as e:
        return {"score": 0, "summary": "Error", "q1": "", "a1": "", "manager_blurb": "", "outreach_email": "", "blind_summary": ""}

# --- EMAIL REPORT ---
def send_summary_email(user_email, df, jd_title):
    msg = MIMEMultipart()
    msg['Subject'] = f"Ranked Candidates: {jd_title}"
    msg['From'] = GMAIL_USER
    msg['To'] = user_email
    
    top_5 = df.head(5)[['Score', 'Name', 'Summary', 'Red Flags']].to_html(index=False)
    
    body = f"""
    <h3>Candidate Ranking Report</h3>
    <p>Attached is the analysis for <strong>{jd_title}</strong>.</p>
    <h4>Top Matches:</h4>
    {top_5}
    """
    msg.attach(MIMEText(body, 'html'))
    
    excel_buffer = io.BytesIO()
    with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer:
        df.to_excel(writer, index=False)
    part = MIMEApplication(excel_buffer.getvalue(), Name="Ranking.xlsx")
    part['Content-Disposition'] = 'attachment; filename="Ranking.xlsx"'
    msg.attach(part)
    
    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as s:
            s.login(GMAIL_USER, GMAIL_APP_PASSWORD)
            s.send_message(msg)
        return True
    except: return False

# --- UI ---
st.set_page_config(page_title="Sharp CV Rank", page_icon="⚖️", layout="wide")

st.title("⚖️ Sharp CV Rank")
st.markdown("### High-Volume Application Screener")

with st.container():
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.info("**🚀 Bulk Processing**\n\nUpload ZIP files or 50+ PDFs at once.")
    with c2:
        st.warning("**🕵️ Fact Checker**\n\nAuto-generates verification questions based on CV claims.")
    with c3:
        st.success("**👻 Outreach**\n\nInstant personalized emails.")
    with c4:
        st.error("**🙈 Blind Hiring**\n\nUnbiased profiles in one click.")

st.divider()

with st.sidebar:
    st.header("1. The Job")
    jd_input_method = st.radio("Input Method", ["Paste Text", "Upload File"])
    
    jd_text = ""
    if jd_input_method == "Paste Text":
        jd_text = st.text_area("Paste JD Here", height=300)
    else:
        jd_file = st.file_uploader("Upload JD", type=["pdf", "docx", "txt"])
        if jd_file:
            jd_text = read_file_content(jd_file, jd_file.name)

    st.divider()
    st.header("2. Settings")
    email_recipient = st.text_input("Email Report To", "judd@sharphuman.com")

st.subheader("2. Upload Candidates")
uploaded_files = st.file_uploader(
    "Upload CVs (PDF, DOCX) or a ZIP file", 
    type=["pdf", "docx", "zip", "txt"], 
    accept_multiple_files=True
)

if st.button("Rank Candidates", type="primary"):
    if not jd_text or not uploaded_files:
        st.error("Missing Data")
    else:
        # 1. Pre-process (Unzip if needed)
        with st.spinner("Unpacking files..."):
            docs = process_uploaded_files(uploaded_files)
        
        st.success(f"Processing {len(docs)} candidates...")
        
        results = []
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        # 2. Analysis Loop
        for i, doc in enumerate(docs):
            status_text.text(f"Forensic Analysis: {doc['name']}...")
            
            a = analyze_candidate(doc['text'], jd_text, doc['name'])
            
            results.append({
                "Score": a.get('score', 0),
                "Name": doc['name'],
                "Summary": a.get('summary', ''),
                "Strengths": a.get('pros', ''),
                "Red Flags": a.get('cons', ''),
                "Manager Blurb": a.get('manager_blurb', ''),
                "Outreach Email": a.get('outreach_email', ''),
                "Blind Summary": a.get('blind_summary', ''),
                "Q1": a.get('q1', ''), "A1": a.get('a1', ''),
                "Q2": a.get('q2', ''), "A2": a.get('a2', ''),
                "Q3": a.get('q3', ''), "A3": a.get('a3', ''),
                "Open Q": a.get('open_q', '')
            })
            progress_bar.progress((i + 1) / len(docs))
            
        status_text.text("Finalizing Report...")
        
        df = pd.DataFrame(results).sort_values(by="Score", ascending=False)
        
        best = df.iloc[0]
        st.balloons()
        st.success(f"🏆 Top Pick: **{best['Name']}** ({best['Score']}%)")
        
        for index, row in df.iterrows():
            with st.expander(f"{row['Score']}% - {row['Name']}"):
                c1, c2 = st.columns([1, 1])
                with c1:
                    st.write("**✅ Strengths**")
                    st.write(row['Strengths'])
                with c2:
                    st.write("**🚩 Red Flags**")
                    st.error(row['Red Flags'])
                
                st.divider()
                
                tab1, tab2, tab3, tab4 = st.tabs(["🕵️ Truth Test", "💬 Slack Blurb", "📧 Outreach", "🙈 Blind Profile"])
                
                with tab1:
                    st.caption("Ask these to verify claims found in the resume:")
                    st.markdown(f"**1. Verify:** {row['Q1']}")
                    st.info(f"Resume says: {row['A1']}")
                    st.markdown(f"**2. Verify:** {row['Q2']}")
                    st.info(f"Resume says: {row['A2']}")
                    st.markdown(f"**3. Verify:** {row['Q3']}")
                    st.info(f"Resume says: {row['A3']}")
                    st.markdown(f"**4. Deep Dive:** {row['Open Q']}")
                
                with tab2:
                    st.code(row['Manager Blurb'], language="text")
                with tab3:
                    st.text_area("Draft Email:", value=row['Outreach Email'], height=150)
                with tab4:
                    st.text_area("Blind Summary:", value=row['Blind Summary'], height=150)

        if email_recipient:
            if send_summary_email(email_recipient, df, "Ranked Report"):
                st.toast("Email Sent!", icon="📧")
