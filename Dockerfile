# Usar una imagen oficial de Linux con Python preinstalado
FROM python:3.11-slim

# Instalar dependencias del sistema operativo (Node.js, npm, Java, wget, curl, unzip)
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

# Establecer el directorio de trabajo
WORKDIR /app

# Copiar todos los archivos del proyecto al contenedor
COPY . /app

# Instalar las dependencias de Python desde requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Dar permisos de ejecución automáticos a los binarios de Luau (crucial para Luraph y Goofyscator)
RUN find . -name "luau" -type f -exec chmod +x {} \;
RUN find . -name "luau-ast" -type f -exec chmod +x {} \;

# Comando para arrancar el bot de Discord
CMD ["python", "bot.py"]
