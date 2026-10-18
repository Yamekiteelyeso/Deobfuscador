# Usar una imagen oficial de Linux que tenga Python y Node.js preinstalados
FROM python:3.11-slim

# Instalar Node.js y npm en el sistema
RUN apt-get update && apt-get install -y nodejs npm && rm -rf /var/lib/apt/lists/*

# Establecer directorio de trabajo
WORKDIR /app

# Copiar los archivos del proyecto
COPY . /app

# Instalar las dependencias de Python
RUN pip install --no-cache-dir -r requirements.txt

# Comando para arrancar el bot
CMD ["python", "bot.py"]
