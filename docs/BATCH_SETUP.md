# Bedrock batch: jednokratno postavljanje

Batch obrada (Bedrock batch inference) košta pola cijene izravnih poziva.
Generator je koristi automatski kad je proizvoda 100 ili više (`--batch auto`,
zadano), a za to treba IAM uloga koju Bedrock preuzima i mjesto u S3.

Račun: **718428650690**, regija **eu-central-1**, S3: **s3://liberiq/bedrock-batch/**.
IAM korisnik `liberiq` (ključevi u `.env`) nema prava na IAM, pa ovo izvodi
administrator računa, svojim profilom.

## 1. Uloga koju preuzima Bedrock (samo prefiks bedrock-batch/)

```bash
cat > trust.json <<'EOF'
{"Version":"2012-10-17","Statement":[{"Effect":"Allow",
 "Principal":{"Service":"bedrock.amazonaws.com"},"Action":"sts:AssumeRole",
 "Condition":{"StringEquals":{"aws:SourceAccount":"718428650690"},
  "ArnLike":{"aws:SourceArn":"arn:aws:bedrock:eu-central-1:718428650690:model-invocation-job/*"}}}]}
EOF
cat > s3.json <<'EOF'
{"Version":"2012-10-17","Statement":[
 {"Effect":"Allow","Action":["s3:GetObject","s3:PutObject"],"Resource":"arn:aws:s3:::liberiq/bedrock-batch/*"},
 {"Effect":"Allow","Action":"s3:ListBucket","Resource":"arn:aws:s3:::liberiq",
  "Condition":{"StringLike":{"s3:prefix":["bedrock-batch/*"]}}}]}
EOF
aws iam create-role --role-name liberiq-bedrock-batch \
  --assume-role-policy-document file://trust.json \
  --description "Bedrock batch za Liberiq PDP generator (samo s3://liberiq/bedrock-batch/)"
aws iam put-role-policy --role-name liberiq-bedrock-batch \
  --policy-name liberiq-bedrock-batch-s3 --policy-document file://s3.json
```

## 2. Prava za korisnika `liberiq` (pokretanje jobova i ulaz/izlaz u S3)

```bash
cat > user.json <<'EOF'
{"Version":"2012-10-17","Statement":[
 {"Effect":"Allow","Action":["bedrock:CreateModelInvocationJob","bedrock:GetModelInvocationJob",
   "bedrock:ListModelInvocationJobs","bedrock:StopModelInvocationJob"],"Resource":"*"},
 {"Effect":"Allow","Action":"iam:PassRole",
  "Resource":"arn:aws:iam::718428650690:role/liberiq-bedrock-batch",
  "Condition":{"StringEquals":{"iam:PassedToService":"bedrock.amazonaws.com"}}},
 {"Effect":"Allow","Action":["s3:GetObject","s3:PutObject"],"Resource":"arn:aws:s3:::liberiq/bedrock-batch/*"},
 {"Effect":"Allow","Action":"s3:ListBucket","Resource":"arn:aws:s3:::liberiq",
  "Condition":{"StringLike":{"s3:prefix":["bedrock-batch/*"]}}}]}
EOF
aws iam put-user-policy --user-name liberiq \
  --policy-name liberiq-bedrock-batch --policy-document file://user.json
```

## 3. U `.env` generatora

```ini
BEDROCK_BATCH_ROLE_ARN=arn:aws:iam::718428650690:role/liberiq-bedrock-batch
BEDROCK_BATCH_S3=s3://liberiq/bedrock-batch
```

## Kako radi

- Svaki proizvod radi u svojoj dretvi; kad svi aktivni proizvodi čekaju model,
  njihovi zahtjevi idu odjednom. Krug s barem 100 zahtjeva za isti model ide kao
  batch job (JSONL u S3, pola cijene); manji krugovi (npr. dodatni pokušaji) idu
  izravnim pozivima. Zapisi koje batch ne obradi ponavljaju se izravno.
- Batch nema prompt caching, pa je ušteda na ulazu nešto manja od 50 %.
- Jedan krug batcha traje od nekoliko minuta do nekoliko sati (Bedrock jamči
  do 24 h); 6.000 proizvoda prolazi u 7 do 10 krugova.
- `--batch off` isključuje batch, `--batch on` ga traži i za manje setove.
- Ulazi i izlazi ostaju u `s3://liberiq/bedrock-batch/<job>/`; mogu se brisati
  nakon runa.
