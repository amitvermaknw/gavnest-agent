READINESS_QUESTIONS = [
    {
        "question_id": "gross_monthly_income",
        "label":       "What's your gross monthly income?",
        "helper":      "Before taxes, including all reliable income sources.",
        "input_type":  "currency",
        "placeholder": "8000",
        "choices":     None,
    },
    {
        "question_id": "monthly_debts",
        "label":       "How much do you pay monthly toward debts?",
        "helper":      "Car loans, credit cards, student loans (not rent/mortgage)",
        "input_type":  "currency",
        "placeholder": "500",
        "choices":     None,
    },
    {
        "question_id": "liquid_savings",
        "label":       "How much do you have saved for a down payment and closing costs?",
        "helper":      "Cash, checking/savings, or investments you could access soon.",
        "input_type":  "currency",
        "placeholder": "20000",
        "choices":     None,
    },
    {
        "question_id": "employment_status",
        "label":       "What's your employment status?",
        "helper":      "This affects how lenders evaluate your income stability.",
        "input_type":  "choice",
        "placeholder": None,
        "choices":     ["W-2 employee", "Self-employed", "1099 contractor", "Retired", "Other"],
    },
]
