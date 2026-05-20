import fasttext
fasttext.FastText.eprint = lambda x: None
model = fasttext.load_model("qobuz_dl/lid.176.ftz")

lines = [
    "Amor",
    "Sentimiento",
    "Para siempre",
    "Mi vida",
    "Tu y yo"
]

for line in lines:
    res = model.predict(line)
    print(f"Line: '{line}' -> {res}")
