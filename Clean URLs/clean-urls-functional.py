import pandas as pd
import os
import re

def clean_file():
    """Clean Excel file based on user input"""
    try:
        # Get input from user
        input_file = input("Enter full path to input Excel file: ").strip()
        output_file = input("Enter full path to output Excel file: ").strip()
        column_name = input("Enter the column name to check (e.g., URL): ").strip()
        
        # Simple pattern input - no regex confusion
        pattern = input("Enter the exact text/pattern to remove rows containing it (e.g., 'otp?', '#respond'): ").strip()
        
        print(f"Looking for pattern: '{pattern}'")
        print("This will remove rows where the column contains this exact text.")

        # Check if input file exists
        if not os.path.exists(input_file):
            print(f"ERROR: Input file not found at: {input_file}")
            return

        print(f"Reading file: {input_file}")
        
        # Read Excel file
        df = pd.read_excel(input_file)
        print(f"Total records loaded: {len(df)}")
        
        # Check if column exists
        if column_name not in df.columns:
            print(f"ERROR: Column '{column_name}' not found!")
            print(f"Available columns: {list(df.columns)}")
            return
        
        print(f"Processing column: {column_name}")
        
        # Convert to string and check for pattern (case insensitive, no regex)
        def contains_pattern(text):
            if pd.isna(text):
                return False
            return str(pattern).lower() in str(text).lower()
        
        # Filter out rows containing the pattern
        mask = df[column_name].apply(contains_pattern)
        removed_count = mask.sum()
        df_cleaned = df[~mask]
        
        print(f"Found {removed_count} rows containing pattern '{pattern}'")
        
        # Save cleaned file
        os.makedirs(os.path.dirname(output_file), exist_ok=True)
        df_cleaned.to_excel(output_file, index=False)
        
        print(f"SUCCESS: Cleaning completed!")
        print(f"Original records: {len(df)}")
        print(f"Removed records: {removed_count}")
        print(f"Cleaned records: {len(df_cleaned)}")
        print(f"Output saved to: {output_file}")
        
        # Show examples of removed URLs (if any)
        if removed_count > 0:
            print("\nExamples of removed URLs:")
            removed_urls = df[mask][column_name].head(5).tolist()
            for url in removed_urls:
                print(f"  - {url}")
        
    except Exception as e:
        print(f"ERROR: {str(e)}")

if __name__ == "__main__":
    clean_file()