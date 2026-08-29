# Import necessary libraries
import pandas as pd
import requests
import json
import sys

# Function to read prompt from text file
def load_prompt_from_file(prompt_file_path):
    try:
        with open(prompt_file_path, 'r', encoding='utf-8') as f:
            prompt_text = f.read().strip()
        return prompt_text
    except Exception as e:
        print(f"Error reading prompt file: {e}")
        sys.exit(1)

# Function to generate content structure using API
def generate_structure(api_key, model, base_prompt, title):
    # Append the title at the end (exactly as you have in your file)
    full_prompt = base_prompt + "\ntitle:\n" + title
    
    # API endpoint
    url = "https://api.ai"
    
    # Headers
    headers = {
        "Authorization": f"Bearer",
        "Content-Type": "application/json"
    }
    
    # Request body
    data = {
        
    }
    
    # Send POST request
    try:
        response = requests.post(url, headers=headers, json=data, timeout=90)
        response.raise_for_status()
        
        result = response.json()
        content = result['choices'][0]['message']['content']
        return content.strip()
        
    except requests.exceptions.RequestException as e:
        print(f"API request failed for title '{title}': {e}")
        if 'response' in locals():
            print(f"Status: {response.status_code} | Response: {response.text[:300]}")
        return None

# Main function
def main(excel_file, prompt_file, api_key, output_file=None, model="grok-beta"):
    # Load the base prompt once from text file
    base_prompt = load_prompt_from_file(prompt_file)
    print("Base prompt loaded successfully.")
    
    # Read the Excel file
    try:
        df = pd.read_excel(excel_file)
    except Exception as e:
        print(f"Error reading Excel file: {e}")
        sys.exit(1)
    
    # Check for required column
    if 'title' not in df.columns:
        print("Error: Excel file must have a 'title' column.")
        sys.exit(1)
    
    # List to collect markdown outputs
    outputs = []
    
    # Process each title
    for index, row in df.iterrows():
        title = str(row['title']).strip()
        if not title:
            print(f"Skipping empty title at row {index+2}")
            continue
            
        print(f"Processing ({index+1}/{len(df)}): {title}")
        
        structure = generate_structure(api_key, model, base_prompt, title)
        
        if structure:
            # Build markdown block
            md_block = f"## {title}\n\n{structure}\n\n---\n\n"
            outputs.append(md_block)
        else:
            outputs.append(f"## {title}\n\n**Failed to generate structure**\n\n---\n\n")
    
    # Combine everything
    full_output = "".join(outputs)
    
    # Save or print
    if output_file:
        try:
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(full_output)
            print(f"\nDone. Output saved to: {output_file}")
        except Exception as e:
            print(f"Error writing output file: {e}")
            print("\nOutput (fallback):\n")
            print(full_output)
    else:
        print("\nOutput:\n")
        print(full_output)

# ────────────────────────────────────────────────
if __name__ == "__main__":
    # ────── Change these paths/values ──────
    excel_file  = "D:\Talasea\Content Brief\Article structure.xlsx"           # your excel file
    prompt_file = "D:\Talasea\Content Brief\prompt.txt"              # your text file with the prompt
    api_key     = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJfaWQiOiI2ODE2NmJjMDk3ZDU5ZGYyZjMxZTMwYWQiLCJpYXQiOjE3Njg5MTA2NjksImV4cCI6MTc2ODk5NzA2OX0.8DtQR1pPhQiG-IK0f8tFZvBxpNhX1nw2NsCRSRtWby8"   # ← your real key
    output_file = "structures_output.md"    # set to None if you want console only
    model       = "grok-beta"               # or "grok-4", etc.
    
    main(excel_file, prompt_file, api_key, output_file, model)
