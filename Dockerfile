# Usar una imagen oficial de Linux que tenga Python preinstalado
FROM python:3.11-slim

# Instalar Node.js, npm, Java (necesario para MoonSec) y herramientas del sistema
RUN apt-get update && apt-get install -y \
    wget \
    curl \
    git \
    unzip \
    default-jdk \
    nodejs \
    npm \
    && rm -rf /var/lib/apt/lists/*

# Instalar .NET 9 SDK (necesario para MoonSec V3)
RUN wget https://dot.net/v1/dotnet-install.sh -O dotnet-install.sh \
    && chmod +x dotnet-install.sh \
    && ./dotnet-install.sh --channel 9.0 --install-dir /usr/share/dotnet \
    && ln -s /usr/share/dotnet/dotnet /usr/bin/dotnet \
    && rm dotnet-install.sh

# Establecer directorio de trabajo
WORKDIR /app

# Copiar los archivos del proyecto
COPY . /app

# Instalar las dependencias de Python
RUN pip install --no-cache-dir -r requirements.txt

# Dar permisos de ejecución automáticos a los binarios de Luau (crucial para Luraph y Goofyscator)
RUN find . -name "luau" -type f -exec chmod +x {} \;
RUN find . -name "luau-ast" -type f -exec chmod +x {} \;

# Comando para arrancar el bot
CMD ["python", "bot.py"]
