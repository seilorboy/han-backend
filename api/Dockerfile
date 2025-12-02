FROM python:3.12-slim

WORKDIR /app

# Asennetaan riippuvuudet
RUN pip install --no-cache-dir flask mysql-connector-python flask-cors

COPY app.py /app/app.py

EXPOSE 5000

CMD ["python", "app.py"]
