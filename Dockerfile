FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV LOJA_HOST=0.0.0.0 LOJA_PORT=8080 LOJA_NO_BROWSER=1 LOJA_DATA_DIR=/data
VOLUME /data
EXPOSE 8080
CMD ["python", "run.py"]
