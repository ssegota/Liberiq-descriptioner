#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Offline test Bedrock batch načina (BatchClient): krugovi zahtjeva, batch job
preko S3, povrat na izravne pozive, trošak po proizvodu. Bez AWS-a."""
import io
import json
import sys
import threading

import pdp_generator as P

FAILURES = []


def check(name, cond, extra=""):
    print(f"[{'OK ' if cond else 'FAIL'}] {name} {extra}")
    if not cond:
        FAILURES.append(name)


class FakeS3:
    def __init__(self):
        self.obj = {}

    def put_object(self, Bucket, Key, Body):
        self.obj[(Bucket, Key)] = Body

    def get_object(self, Bucket, Key):
        return {"Body": io.BytesIO(self.obj[(Bucket, Key)])}

    def get_paginator(self, _name):
        s3 = self

        class Pag:
            def paginate(self, Bucket, Prefix):
                return [{"Contents": [{"Key": k} for (b, k) in s3.obj
                                      if b == Bucket and k.startswith(Prefix)]}]
        return Pag()


class FakeBedrock:
    """Batch job odmah završi; zapis r000003 namjerno pada (ide izravno)."""

    def __init__(self, s3):
        self.s3, self.jobs = s3, []

    def create_model_invocation_job(self, jobName, roleArn, modelId, inputDataConfig,
                                    outputDataConfig):
        uri_in = inputDataConfig["s3InputDataConfig"]["s3Uri"][5:]
        bucket, _, key = uri_in.partition("/")
        izlaz = []
        for redak in self.s3.obj[(bucket, key)].decode().splitlines():
            r = json.loads(redak)
            assert r["modelInput"]["anthropic_version"] == "bedrock-2023-05-31"
            if r["recordId"] == "r000003":
                izlaz.append({"recordId": r["recordId"], "error": {"errorMessage": "x"}})
                continue
            tekst = r["modelInput"]["messages"][0]["content"][0]["text"]
            izlaz.append({"recordId": r["recordId"], "modelOutput": {
                "content": [{"type": "text", "text": f"BATCH:{tekst}"}],
                "usage": {"input_tokens": 1000, "output_tokens": 100}}})
        out_prefix = outputDataConfig["s3OutputDataConfig"]["s3Uri"][5:].partition("/")[2]
        self.s3.put_object(bucket, f"{out_prefix}input.jsonl.out",
                           "\n".join(json.dumps(x) for x in izlaz).encode())
        self.jobs.append({"model": modelId, "role": roleArn, "n": len(izlaz)})
        return {"jobArn": f"arn:job/{jobName}"}

    def get_model_invocation_job(self, jobIdentifier):
        return {"status": "Completed"}


CONFIG = {"BEDROCK_TEXT_MODEL_ID": "eu.anthropic.claude-sonnet-4-6",
          "BEDROCK_VERIFY_MODEL_ID": "eu.anthropic.claude-sonnet-4-6",
          "BEDROCK_RESCUE_MODEL_ID": "eu.anthropic.claude-opus-5-5",
          "BEDROCK_AWS_REGION": "eu-central-1", "BEDROCK_AWS_ACCESS_KEY_ID": "x",
          "BEDROCK_AWS_SECRET_ACCESS_KEY": "y",
          "BEDROCK_BATCH_ROLE_ARN": "arn:aws:iam::1:role/liberiq-bedrock-batch",
          "BEDROCK_BATCH_S3": "s3://liberiq/bedrock-batch"}


class TestBatchClient(P.BatchClient):
    izravnih = 0

    def _converse(self, model_id, system_prompt, user_message, max_tokens,
                  temperature, effort=None):
        TestBatchClient.izravnih += 1
        self._zabiljezi(model_id, {"inputTokens": 1000, "outputTokens": 100})
        return f"IZRAVNO:{user_message}"


check("batch nije spreman bez uloge",
      not P.batch_spreman({**CONFIG, "BEDROCK_BATCH_ROLE_ARN": ""}))
check("batch spreman s ulogom i S3", P.batch_spreman(CONFIG))

s3 = FakeS3()
br = FakeBedrock(s3)
c = TestBatchClient(CONFIG, poll_s=0, bedrock=br, s3=s3)
N = 120
odgovori, troskovi = {}, {}


def proizvod(i):
    try:
        prije = c.usage_dretve()
        odgovori[i] = c.generate("sustav", f"p{i}")
        poslije = c.usage_dretve()
        troskovi[i] = {m: {k: v - prije.get(m, {}).get(k, 0) for k, v in u.items()}
                       for m, u in poslije.items()}
    finally:
        c.zavrsi()


for _ in range(N):
    c.pocni()
dretve = [threading.Thread(target=proizvod, args=(i,)) for i in range(N)]
for d in dretve:
    d.start()
for d in dretve:
    d.join(timeout=60)
check("svih 120 proizvoda dobilo odgovor", len(odgovori) == N)
check("jedan batch job za 120 zahtjeva", len(br.jobs) == 1 and br.jobs[0]["n"] == N,
      str(br.jobs))
check("odgovor pripada svom proizvodu", odgovori.get(7) == "BATCH:p7")
check("zapis koji batch nije obradio ide izravno",
      odgovori.get(3) == "IZRAVNO:p3" and TestBatchClient.izravnih == 1)
check("uloga i model u jobu", br.jobs[0]["role"].endswith("liberiq-bedrock-batch")
      and br.jobs[0]["model"] == CONFIG["BEDROCK_TEXT_MODEL_ID"])
k = "eu.anthropic.claude-sonnet-4-6" + P.BATCH_SUFIKS
check("potrošnja batcha bilježi se po proizvodu", troskovi.get(7, {}).get(k, {}).get("poziva") == 1,
      str(troskovi.get(7)))
check("izravni poziv bilježi se po proizvodu",
      troskovi.get(3, {}).get("eu.anthropic.claude-sonnet-4-6", {}).get("poziva") == 1,
      str(troskovi.get(3)))
cijena_batch = P.trosak_usd(troskovi[7])
cijena_izravno = P.trosak_usd(troskovi[3])
check("batch je pola cijene (EU profil +10 % u oba)", abs(cijena_batch * 2 - cijena_izravno) < 1e-9,
      f"({cijena_batch:.4f} vs {cijena_izravno:.4f})")

check("EU profil 10 % skuplji od globalnog",
      abs(P.trosak_usd({"eu.anthropic.claude-sonnet-4-6": {"input": 1_000_000}}) - 3.30) < 1e-9
      and abs(P.trosak_usd({"global.anthropic.claude-sonnet-4-6": {"input": 1_000_000}}) - 3.00) < 1e-9)

# mali krug (< 100) ide izravno
c2 = TestBatchClient(CONFIG, poll_s=0, bedrock=FakeBedrock(s3), s3=s3)
TestBatchClient.izravnih = 0
mali = {}


def mali_proizvod(i):
    try:
        mali[i] = c2.extract("s", f"m{i}")
    finally:
        c2.zavrsi()


for _ in range(5):
    c2.pocni()
ds = [threading.Thread(target=mali_proizvod, args=(i,)) for i in range(5)]
for d in ds:
    d.start()
for d in ds:
    d.join(timeout=30)
check("krug manji od 100 ide izravnim pozivima",
      len(mali) == 5 and TestBatchClient.izravnih == 5 and not c2._bedrock.jobs)
c.zatvori()
c2.zatvori()

# tijelo zahtjeva: Opus bez temperature, s effortom i prostorom za razmišljanje
t = c._tijelo({"model": "eu.anthropic.claude-opus-5-5", "max_tokens": 8000,
               "temperature": 0.3, "effort": "low", "system": "s", "user": "u"})
check("Opus u batchu: bez temperature, effort low, +prostor za thinking",
      "temperature" not in t and t["output_config"] == {"effort": "low"}
      and t["max_tokens"] == 8000 + P.THINKING_HEADROOM)
t2 = c._tijelo({"model": "eu.anthropic.claude-sonnet-4-6", "max_tokens": 3000,
                "temperature": 0.0, "effort": None, "system": "s", "user": "u"})
check("Sonnet u batchu: s temperaturom, bez efforta",
      t2["temperature"] == 0.0 and "output_config" not in t2)

print()
if FAILURES:
    print("PALO:", FAILURES)
    sys.exit(1)
print("Sve OK.")
