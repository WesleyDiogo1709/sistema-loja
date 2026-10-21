FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
# Produção: HTTPS fica por conta da hospedagem (proxy); o banco e os backups vão para o disco persistente /data.
ENV LOJA_ENV=production LOJA_DATA_DIR=/data LOJA_NO_BROWSER=1 PORT=8080
VOLUME /data
EXPOSE 8080
HEALTHCHECK --interval=60s --timeout=5s --start-period=20s CMD python -c "import os,urllib.request;urllib.request.urlopen('http://127.0.0.1:%s/api/health'%os.environ.get('PORT','8080'),timeout=4)" || exit 1
CMD ["python", "run.py"]
