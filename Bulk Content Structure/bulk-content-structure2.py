# Import necessary libraries
import pandas as pd
import requests
import json
import sys

# ────────────────────────────────────────────────
# CONFIG - CHANGE THESE
# ────────────────────────────────────────────────
API_URL       = "https://api.kasku.ai/chat/tls"          # ← آدرس واقعی API رو اینجا بذار
BEARER_TOKEN  = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJfaWQiOiI2ODE2NmJjMDk3ZDU5ZGYyZjMxZTMwYWQiLCJpYXQiOjE3Njg5MTA2NjksImV4cCI6MTc2ODk5NzA2OX0.8DtQR1pPhQiG-IK0f8tFZvBxpNhX1nw2NsCRSRtWby8"  # ← توکن کامل
SESSION_ID    = "696f6f5d336f5b00e38b37ff"                # ← session id ثابت یا متغیر
# ────────────────────────────────────────────────

# Function to read prompt from text file
def load_prompt_from_file(prompt_file_path):
    try:
        with open(prompt_file_path, 'r', encoding='utf-8') as f:
            prompt_text = f.read().strip()
        return prompt_text
    except Exception as e:
        print(f"Error reading prompt file: {e}")
        sys.exit(1)

# Function to generate content structure using the custom API
def generate_structure(bearer_token, session_id, base_prompt, title, api_url):
    # Append title exactly as in your file
    full_prompt = base_prompt + "\ntitle:\n" + title
    
    # Prepare JSON body (as per your example)
    payload = {
        "sessionId": session_id,
        "prompt": full_prompt
    }
    
    # Headers
    headers = {
        "Authorization": f"Bearer {bearer_token}",
        "Content-Type": "application/json",
        "Accept": "application/json"   # optional but good practice
    }
    
    try:
        response = requests.post(
            api_url,
            headers=headers,
            json=payload,          # sends as JSON
            timeout=120
        )
        response.raise_for_status()
        
        data = response.json()
        
        # Try to extract the answer - adjust keys based on real response
        # Common patterns:
        if "response" in data:
            return data["response"].strip()
        elif "text" in data:
            return data["text"].strip()
        elif "content" in data:
            return data["content"].strip()
        elif "message" in data:
            return data["message"].strip()
        else:
            # fallback: return whole response as string if unsure
            print("Unknown response format:", json.dumps(data, ensure_ascii=False, indent=2))
            return str(data)
            
    except requests.exceptions.RequestException as e:
        print(f"API request failed for title '{title}': {e}")
        if 'response' in locals():
            print(f"Status: {response.status_code} | Body: {response.text[:400]}")
        return None

# Main function
def main(excel_file, prompt_file, output_dir="structures", create_separate_files=True):
    # Load base prompt once
    base_prompt = load_prompt_from_file(prompt_file)
    print("Base prompt loaded successfully.")
    
    # Read Excel
    try:
        df = pd.read_excel(excel_file)
    except Exception as e:
        print(f"Error reading Excel: {e}")
        sys.exit(1)
    
    if 'title' not in df.columns:
        print("Error: Excel must have 'title' column.")
        sys.exit(1)
    
    # ایجاد پوشه خروجی اگر وجود ندارد
    import os
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
        print(f"Created output directory: {output_dir}")
    
    processed_count = 0
    
    for index, row in df.iterrows():
        title = str(row['title']).strip()
        if not title:
            print(f"Skipping empty title at row {index+2}")
            continue
            
        print(f"Processing ({index+1}/{len(df)}): {title}")
        
        structure = generate_structure(
            bearer_token=BEARER_TOKEN,
            session_id=SESSION_ID,
            base_prompt=base_prompt,
            title=title,
            api_url=API_URL
        )
        
        if not structure:
            structure = "**Failed to generate structure**"
        
        # Create md file
        md_content = f"# {title}\n\n{structure}\n"
        
        #Create md file content
        safe_title = "".join(c for c in title if c.isalnum() or c in " -_()").strip()
        if not safe_title:
            safe_title = f"title_{index+1}"
        
        filename = f"{safe_title}.md"
        filepath = os.path.join(output_dir, filename)
        
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(md_content)
            print(f"  Saved: {filepath}")
            processed_count += 1
        except Exception as e:
            print(f"  Failed to save {filename}: {e}")
    
    print(f"\nDone. {processed_count} file(s) created in folder: {output_dir}")
# ────────────────────────────────────────────────
if __name__ == "__main__":
    # ────── CHANGE THESE ──────
    excel_file  = "D:\Talasea\Content Brief\Article structure.xlsx"
    prompt_file = "D:\Talasea\Content Brief\prompt.txt"
    output_directory = "D:\Talasea\Content Brief\Bulk-structures"
    
    
    main(excel_file, prompt_file, output_dir=output_directory)