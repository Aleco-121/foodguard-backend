#!/bin/bash

# Script de verificación pre-despliegue
# Este script verifica que todo esté listo para desplegar en Render

echo "🔍 Verificando configuración para despliegue..."
echo ""

# Colores
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Contador de errores
ERRORS=0
WARNINGS=0

# 1. Verificar que estamos en el directorio correcto
echo "📁 Verificando directorio..."
if [ -f "main.py" ] && [ -f "Dockerfile" ]; then
    echo -e "${GREEN}✅ Directorio correcto${NC}"
else
    echo -e "${RED}❌ Error: No se encuentra main.py o Dockerfile${NC}"
    echo "   Ejecuta este script desde el directorio backend/"
    exit 1
fi
echo ""

# 2. Verificar Dockerfile
echo "🐳 Verificando Dockerfile..."
if grep -q "gunicorn" Dockerfile && grep -q "PORT" Dockerfile; then
    echo -e "${GREEN}✅ Dockerfile configurado correctamente${NC}"
else
    echo -e "${RED}❌ Error: Dockerfile no está configurado correctamente${NC}"
    ERRORS=$((ERRORS + 1))
fi
echo ""

# 3. Verificar requirements.txt
echo "📦 Verificando requirements.txt..."
REQUIRED_PACKAGES=("fastapi" "uvicorn" "gunicorn" "httpx" "supabase")
for package in "${REQUIRED_PACKAGES[@]}"; do
    if grep -q "$package" requirements.txt; then
        echo -e "${GREEN}✅ $package encontrado${NC}"
    else
        echo -e "${RED}❌ Falta: $package${NC}"
        ERRORS=$((ERRORS + 1))
    fi
done
echo ""

# 4. Verificar .gitignore
echo "🔒 Verificando .gitignore..."
if grep -q ".env" .gitignore; then
    echo -e "${GREEN}✅ .env está en .gitignore${NC}"
else
    echo -e "${RED}❌ Advertencia: .env no está en .gitignore${NC}"
    WARNINGS=$((WARNINGS + 1))
fi
echo ""

# 5. Verificar que .env NO esté en git
echo "🔐 Verificando que .env no esté en el repositorio..."
if git ls-files | grep -q "^.env$"; then
    echo -e "${RED}❌ PELIGRO: .env está siendo rastreado por git${NC}"
    echo "   Ejecuta: git rm --cached .env"
    ERRORS=$((ERRORS + 1))
else
    echo -e "${GREEN}✅ .env no está en el repositorio${NC}"
fi
echo ""

# 6. Verificar variables de entorno necesarias
echo "🔑 Verificando variables de entorno en .env..."
if [ -f ".env" ]; then
    if grep -q "GEMINI_API_KEY" .env && grep -q "SUPABASE_URL" .env && grep -q "SUPABASE_KEY" .env; then
        echo -e "${GREEN}✅ Todas las variables necesarias están en .env${NC}"
        echo -e "${YELLOW}⚠️  Recuerda copiarlas a Render${NC}"
    else
        echo -e "${RED}❌ Faltan variables en .env${NC}"
        ERRORS=$((ERRORS + 1))
    fi
else
    echo -e "${YELLOW}⚠️  Archivo .env no encontrado (opcional para local)${NC}"
    WARNINGS=$((WARNINGS + 1))
fi
echo ""

# 7. Verificar repositorio Git
echo "📡 Verificando repositorio Git..."
if git remote -v | grep -q "github.com"; then
    REPO_URL=$(git remote get-url origin)
    echo -e "${GREEN}✅ Repositorio configurado: $REPO_URL${NC}"
else
    echo -e "${RED}❌ No hay repositorio de GitHub configurado${NC}"
    ERRORS=$((ERRORS + 1))
fi
echo ""

# 8. Verificar estado de Git
echo "📝 Verificando estado de Git..."
if [ -z "$(git status --porcelain)" ]; then
    echo -e "${GREEN}✅ No hay cambios sin commitear${NC}"
else
    echo -e "${YELLOW}⚠️  Hay cambios sin commitear:${NC}"
    git status --short
    WARNINGS=$((WARNINGS + 1))
fi
echo ""

# 9. Verificar que estamos actualizados con origin
echo "🔄 Verificando sincronización con GitHub..."
git fetch origin main 2>/dev/null
LOCAL=$(git rev-parse @)
REMOTE=$(git rev-parse @{u} 2>/dev/null)

if [ "$LOCAL" = "$REMOTE" ]; then
    echo -e "${GREEN}✅ Código local sincronizado con GitHub${NC}"
else
    echo -e "${YELLOW}⚠️  El código local no está sincronizado con GitHub${NC}"
    echo "   Ejecuta: git push origin main"
    WARNINGS=$((WARNINGS + 1))
fi
echo ""

# 10. Verificar estructura de archivos
echo "📂 Verificando estructura de archivos..."
REQUIRED_FILES=("main.py" "requirements.txt" "Dockerfile" ".dockerignore")
for file in "${REQUIRED_FILES[@]}"; do
    if [ -f "$file" ]; then
        echo -e "${GREEN}✅ $file existe${NC}"
    else
        echo -e "${RED}❌ Falta: $file${NC}"
        ERRORS=$((ERRORS + 1))
    fi
done
echo ""

# Resumen final
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
if [ $ERRORS -eq 0 ] && [ $WARNINGS -eq 0 ]; then
    echo -e "${GREEN}🎉 ¡TODO LISTO PARA DESPLEGAR!${NC}"
    echo ""
    echo "Próximos pasos:"
    echo "1. Ve a https://render.com"
    echo "2. Crea un nuevo Web Service"
    echo "3. Conecta tu repositorio: $(git remote get-url origin)"
    echo "4. Configura las variables de entorno desde tu .env"
    echo "5. ¡Despliega!"
elif [ $ERRORS -eq 0 ]; then
    echo -e "${YELLOW}⚠️  LISTO CON ADVERTENCIAS${NC}"
    echo ""
    echo "Tienes $WARNINGS advertencia(s) pero puedes continuar."
    echo "Revisa las advertencias arriba antes de desplegar."
else
    echo -e "${RED}❌ HAY ERRORES QUE CORREGIR${NC}"
    echo ""
    echo "Encontrados $ERRORS error(es) y $WARNINGS advertencia(s)."
    echo "Por favor, corrige los errores antes de desplegar."
    exit 1
fi
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
