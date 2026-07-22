MORTGAGE_QUESTIONS = [
    {
        "id":          "target_home_price",
        "label":       "What's the price range of homes you're looking at?",
        "helper":      "This helps Gavvy find the most relevant lenders and rates",
        "input_type":  "choice",
        "choices":     [
            "Under $250k",
            "$250k-$350k",
            "$350k-$500k",
            "$500k-$750k",
            "Over $750k",
        ],
    },
    {
        "id":          "down_payment_amount",
        "label":       "How much are you putting down?",
        "helper":      "Exact amount is fine — we'll calculate the percentage",
        "input_type":  "currency",
        "placeholder": "85000",
    },
    {
        "id":          "has_existing_lender",
        "label":       "Have you already talked to a lender?",
        "helper":      "No pressure either way — helps Gavvy know where you are",
        "input_type":  "choice",
        "choices":     [
            "No, haven't started",
            "Yes, got a pre-qual letter",
            "Yes, have a full pre-approval",
            "Shopping multiple lenders now",
        ],
    },
    {
        "id":          "loan_type_preference",
        "label":       "Do you have a loan type preference?",
        "helper":      "Gavvy will explain tradeoffs if you're unsure",
        "input_type":  "choice",
        "choices":     [
            "Conventional (20%+ down)",
            "FHA (lower down payment)",
            "VA (military/veteran)",
            "Not sure — help me decide",
        ],
    },
]