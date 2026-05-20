import fasttext
fasttext.FastText.eprint = lambda x: None
model = fasttext.load_model("qobuz_dl/lid.176.ftz")

lines = [
    "Corazón",
    "Te amo mi amor",
    "Baila conmigo",
    "Yo quiero",
    "Una noche más"
]

for line in lines:
    res = model.predict(line)
    print(f"Line: '{line}' -> {res}")
