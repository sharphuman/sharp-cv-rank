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

# --- CONFIGURATION ---
OPENAI_API_KEY = st.secrets["OPENAI_API_KEY"]
GMAIL_USER = st.secrets["GMAIL_USER"]
GMAIL_APP_PASSWORD = st.secrets["GMAIL_APP_PASSWORD"]

client = OpenAI(api_key=OPENAI_API_KEY)

# --- HELPER: FILE PROCESSING ---
def read_file_content(file_obj, filename):
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
    return text[:4000]

def process_uploaded_files(uploaded_files):
    processed_docs = []
    for uploaded_file in uploaded_files:
        if uploaded_file.name.lower().endswith(".zip"):
            try:
                with zipfile.ZipFile(uploaded_file) as z:
                    for filename in z.namelist():
                        if "__MACOSX" in filename or filename.endswith("/"): continue
                        if filename.lower().endswith(('.pdf', '.docx', '.txt')):
                            with z.open(filename) as f:
                                file_content = io.BytesIO(f.read())
                                text = read_file_content(file_content, filename)
                                processed_docs.append({"name": filename, "text": text})
            except: pass
        else:
            text = read_file_content(uploaded_file, uploaded_file.name)
            processed_docs.append({"name": uploaded_file.name, "text": text})
    return processed_docs

# --- AI ANALYSIS ---
def analyze_candidate(candidate_text, jd_text, filename):
    prompt = f"""
    You are a Senior Technical Recruiter. Evaluate this candidate.
    
    JOB DESCRIPTION:
    {jd_text[:2000]}
    
    CANDIDATE CV:
    {candidate_text[:3000]}
    
    TASK:
    1. Score (0-100): Strict match.
    2. Summary: 2 sentences.
    3. Red Flags: Gaps, hopping, missing skills.
    
    4. KNOWLEDGE CHECK (The "Knock-out" Test):
       - Identify the TOP 3 HARD SKILLS listed (e.g. Active Directory, Python, AWS).
       - Create 3 "Trivia" questions to test basic competence. (e.g. "What are the 5 FSMO roles?").
       - Provide the CORRECT ANSWER for the recruiter.
    
    5. BEHAVIORAL DEEP DIVE (The "Open" Questions):
       - Q1: "Describe a time you had to DEPLOY or DESIGN something complex..." (Contextualize this to a project in their CV).
       - Q2: "Describe a time you had to SOLVE a very complex problem..." (Contextualize this to a specific role/tech in their CV).
    
    6. EXTRAS:
       - Manager Blurb (for Slack).
       - Outreach Email (Personalized).
       - Blind Profile (No Name/Gender).
    
    OUTPUT JSON KEYS: 
    "score", "summary", "pros", "cons", 
    "tech_q1", "tech_a1", "tech_q2", "tech_a2", "tech_q3", "tech_a3", 
    "beh_q1", "beh_q2",
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
        return {"score": 0, "summary": "Error", "tech_q1": "", "tech_a1": "", "manager_blurb": "", "outreach_email": "", "blind_summary": ""}

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
st.markdown("### The Technical Screen Helper")

with st.container():
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.info("**🚀 Bulk Processing**\n\nZIP / PDF support.")
    with c2:
        st.warning("**🧠 Knowledge Check**\n\nAuto-generated tech trivia + answers.")
    with c3:
        st.success("**💬 Behavioral**\n\nCustomized 'Tell me about a time' prompts.")
    with c4:
        st.error("**🙈 Blind Hiring**\n\nUnbiased profiles.")

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
        with st.spinner("Unpacking files..."):
            docs = process_uploaded_files(uploaded_files)
        
        st.success(f"Processing {len(docs)} candidates...")
        
        results = []
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        for i, doc in enumerate(docs):
            status_text.text(f"Screening: {doc['name']}...")
            
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
                "TQ1": a.get('tech_q1', ''), "TA1": a.get('tech_a1', ''),
                "TQ2": a.get('tech_q2', ''), "TA2": a.get('tech_a2', ''),
                "TQ3": a.get('tech_q3', ''), "TA3": a.get('tech_a3', ''),
                "BQ1": a.get('beh_q1', ''), "BQ2": a.get('beh_q2', '')
            })
            progress_bar.progress((i + 1) / len(docs))
            
        status_text.text("Finalizing...")
        
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
                
                # RECRUITER TOOLS
                tab1, tab2, tab3, tab4, tab5 = st.tabs(["🧠 Knowledge Check", "🗣️ Behavioral", "💬 Slack", "📧 Outreach", "🙈 Blind Profile"])
                
                with tab1:
                    st.caption("Ask these to test basic technical competence:")
                    col_q, col_a = st.columns([2, 1])
                    
                    with col_q:
                        st.markdown(f"**Q1:** {row['TQ1']}")
                        st.markdown(f"**Q2:** {row['TQ2']}")
                        st.markdown(f"**Q3:** {row['TQ3']}")
                    with col_a:
                        st.info(f"**Answer:** {row['TA1']}")
                        st.info(f"**Answer:** {row['TA2']}")
                        st.info(f"**Answer:** {row['TA3']}")

                with tab2:
                    st.caption("Ask these to test experience depth:")
                    st.markdown(f"**1. Deployment/Design:**\n> {row['BQ1']}")
                    st.markdown(f"**2. Complex Problem:**\n> {row['BQ2']}")
                
                with tab3:
                    st.code(row['Manager Blurb'], language="text")
                with tab4:
                    st.text_area("Draft Email:", value=row['Outreach Email'], height=150)
                with tab5:
                    st.text_area("Blind Summary:", value=row['Blind Summary'], height=150)

        if email_recipient:
            if send_summary_email(email_recipient, df, "Ranked Report"):
                st.toast("Email Sent!", icon="📧")
