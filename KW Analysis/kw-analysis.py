import pandas as pd
import re
import os

def normalize_persian_text(text):
    """Normalize Persian text: remove ZWNJ, extra spaces, normalize whitespace."""
    if pd.isna(text):
        return ""
    text = str(text)
    # Remove ZWNJ (Zero-Width Non-Joiner) and other invisible chars
    text = text.replace('\u200c', '').replace('\u200d', '').replace('\u2066', '').replace('\u2067', '')
    # Normalize all whitespace to single space
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

def clean_keyword_data():
    """Clean keyword data with multi-word and regex filters (Persian-safe)."""
    
    input_path = input("Enter input file path: ").strip()
    output_path = input("Enter output file path: ").strip()
    query_column = input("Enter query column name: ").strip()
    
    min_words_input = input("Enter min word count (e.g., 2) or press Enter to skip: ").strip()
    min_words = int(min_words_input) if min_words_input.isdigit() else None
    
    regex_input = input("Enter regex pattern (e.g., چرا|چطور|کجا) or press Enter to skip: ").strip()
    regex_compiled = re.compile(regex_input, re.IGNORECASE) if regex_input else None
    
    # Validate file
    if not os.path.exists(input_path):
        print(f"ERROR: File not found: {input_path}")
        return
    
    # Read file
    ext = os.path.splitext(input_path)[1].lower()
    try:
        df = pd.read_csv(input_path) if ext == '.csv' else pd.read_excel(input_path)
    except Exception as e:
        print(f"ERROR reading file: {e}")
        return
    
    if query_column not in df.columns:
        print(f"ERROR: Column '{query_column}' not found.")
        print(f"Available: {list(df.columns)}")
        return
    
    print(f"Loaded {len(df):,} rows from column '{query_column}'")
    
    # Normalize all queries first
    print("Normalizing Persian text (removing ZWNJ, extra spaces)...")
    df['normalized_query'] = df[query_column].apply(normalize_persian_text)
    
    filtered = df.copy()
    applied_filters = []
    
    # Multi-word filter (on normalized text)
    if min_words is not None:
        def word_count(text):
            return len(text.split()) if text else 0
        mask = filtered['normalized_query'].apply(word_count) >= min_words
        filtered = filtered[mask]
        applied_filters.append(f">= {min_words} words")
        print(f"Applied: >= {min_words} words → {len(filtered):,} rows")
    
    # Regex filter (on normalized text)
    if regex_compiled is not None:
        def has_pattern(text):
            if not text:
                return False
            return bool(regex_compiled.search(text))
        mask = filtered['normalized_query'].apply(has_pattern)
        filtered = filtered[mask]
        applied_filters.append(f"regex: {regex_input}")
        print(f"Applied: regex '{regex_input}' → {len(filtered):,} rows")
    
    # Final result
    if not applied_filters:
        print("No filters applied. Copying all data...")
    else:
        print(f"Filters applied: {', '.join(applied_filters)}")
    
    # Keep only original columns (drop helper)
    result = filtered.drop(columns=['normalized_query'])
    
    # Save
    try:
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        if ext == '.csv' or output_path.endswith('.csv'):
            result.to_csv(output_path, index=False)
        else:
            result.to_excel(output_path, index=False)
        print(f"SUCCESS: {len(result):,} rows saved to {output_path}")
    except Exception as e:
        print(f"ERROR saving: {e}")

if __name__ == "__main__":
    clean_keyword_data()