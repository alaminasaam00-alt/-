FROM python:3.13-slim
WORKDIR /app
COPY numo/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY numo/app.py ./app.py
ENV PYTHONUNBUFFERED=1
EXPOSE 10000
CMD ["uvicorn","app:app","--host","0.0.0.0","--port","10000"]
