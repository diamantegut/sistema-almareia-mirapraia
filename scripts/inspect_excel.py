import pandas as pd
import os

files = [
    r"F:\info Fiscal\PRODUTOS (250).xlsx",
    r"F:\info Fiscal\PRODUTOS POR TAMANHO (27).xlsx"
]

for f in files:
    print(f"\nAnalyzing: {f}")
    try:
        df = pd.read_excel(f)
        print("Columns:", list(df.columns))
        print("First row:", df.iloc[0].to_dict())
    except Exception as e:
        print(f"Error reading {f}: {e}")
