# 🛡️ FoodGuard Elite - Backend API

Backend de la aplicación FoodGuard Elite, un sistema avanzado de análisis nutricional y detección de aditivos alimentarios.

## 🚀 Características

- **Análisis de Códigos de Barras**: Integración con OpenFoodFacts para obtener información nutricional
- **Detección de Aditivos**: Base de datos clínica de 50+ aditivos con perfiles de riesgo
- **IA con Gemini**: Análisis de imágenes de ingredientes y generación de recetas
- **Filtros Personalizados**: Gluten, lactosa, vegano, vegetariano, MSG, aceite de palma, etc.
- **Historial de Escaneos**: Guardado en Supabase Cloud o SQLite local
- **Alternativas Saludables**: Sugerencias automáticas de productos más sanos
- **Sistema de Puntuación**: Algoritmo tipo Nutri-Score mejorado (0-100)

## 🛠️ Tecnologías

- **Framework**: FastAPI
- **Base de Datos**: Supabase (PostgreSQL) / SQLite (fallback local)
- **IA**: Google Gemini 2.0 Flash
- **Autenticación**: Bcrypt + passlib
- **Servidor**: Gunicorn + Uvicorn workers
- **Contenedor**: Docker

## 📋 Requisitos

- Python 3.10+
- Cuenta de Supabase (opcional, usa SQLite si no está configurada)
- API Key de Google Gemini

## 🔧 Instalación Local

### 1. Clonar el repositorio
```bash
git clone https://github.com/Aleco-121/foodguard-backend.git
cd foodguard-backend
```

### 2. Crear entorno virtual
```bash
python3 -m venv venv
source venv/bin/activate  # En Windows: venv\Scripts\activate
```

### 3. Instalar dependencias
```bash
pip install -r requirements.txt
```

### 4. Configurar variables de entorno
Crea un archivo `.env` en la raíz:
```env
GEMINI_API_KEY=tu_clave_de_gemini
SUPABASE_URL=https://tu-proyecto.supabase.co
SUPABASE_KEY=tu_clave_de_supabase
```

### 5. Ejecutar el servidor
```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

El servidor estará disponible en `http://localhost:8000`

## 🐳 Ejecutar con Docker

```bash
docker build -t foodguard-backend .
docker run -p 8000:8000 \
  -e GEMINI_API_KEY=tu_clave \
  -e SUPABASE_URL=tu_url \
  -e SUPABASE_KEY=tu_clave \
  foodguard-backend
```

## 🌐 Despliegue en Render

### Opción 1: Desde el Dashboard (Recomendado)

1. Ve a [render.com](https://render.com) y regístrate
2. Click en **"New +"** → **"Web Service"**
3. Conecta este repositorio
4. Configura:
   - **Environment**: Docker
   - **Region**: Frankfurt (EU Central)
   - **Instance Type**: Free (o Starter para producción)
5. Añade las variables de entorno:
   - `GEMINI_API_KEY`
   - `SUPABASE_URL`
   - `SUPABASE_KEY`
6. Click en **"Create Web Service"**

### Opción 2: Desde CLI

```bash
# Instalar Render CLI
brew install render  # macOS
# o descargar desde https://render.com/docs/cli

# Autenticar
render login

# Desplegar
render deploy
```

## 📚 Documentación de la API

Una vez desplegado, la documentación interactiva estará disponible en:
- **Swagger UI**: `https://tu-app.onrender.com/docs`
- **ReDoc**: `https://tu-app.onrender.com/redoc`

## 🔑 Endpoints Principales

### Autenticación
- `POST /register` - Registrar nuevo usuario
- `POST /login` - Iniciar sesión

### Análisis
- `POST /analyze` - Analizar producto por código de barras
- `POST /analyze-ingredients-image` - Analizar imagen de ingredientes con IA
- `POST /alternatives` - Obtener alternativas más saludables

### Recetas IA
- `POST /generate-recipes` - Generar recetas con Gemini AI

### Usuario
- `GET /history/{username}` - Obtener historial de escaneos
- `POST /save-settings` - Guardar preferencias del usuario
- `GET /daily-tip` - Obtener consejo del día

## 🗄️ Estructura de la Base de Datos

### Tabla `users`
```sql
username TEXT PRIMARY KEY
password TEXT (hashed con bcrypt)
settings TEXT (JSON con filtros y preferencias)
last_active DATETIME
```

### Tabla `history`
```sql
id INTEGER PRIMARY KEY
username TEXT (FK)
barcode TEXT
product_name TEXT
status TEXT (SAFE/WARNING)
score INTEGER (0-100)
timestamp DATETIME
```

## 🔒 Seguridad

- ✅ Contraseñas hasheadas con bcrypt
- ✅ Variables de entorno para secretos
- ✅ HTTPS obligatorio en producción
- ✅ CORS configurado
- ✅ Rate limiting (recomendado añadir)

## 🧪 Testing

```bash
# Probar endpoint de salud
curl https://tu-app.onrender.com/daily-tip

# Probar análisis de producto
curl -X POST https://tu-app.onrender.com/analyze \
  -H "Content-Type: application/json" \
  -d '{
    "barcode": "8480000818607",
    "settings": {"gluten_free": true}
  }'
```

## 📊 Monitoreo

### Logs en Render
```bash
# Ver logs en tiempo real
render logs -f
```

### Métricas
- CPU y memoria en el dashboard de Render
- Logs de peticiones en tiempo real
- Alertas configurables

## 🐛 Solución de Problemas

### Error: "Application failed to respond"
- Verificar que el `PORT` se esté usando correctamente
- Revisar logs en Render

### Error: "Database connection failed"
- Verificar variables de entorno
- Comprobar que Supabase esté activo

### Error: "Build failed"
- Verificar que `requirements.txt` esté completo
- Asegurarse de que el Dockerfile esté en la raíz

## 📈 Roadmap

- [ ] Rate limiting con Redis
- [ ] Caché de respuestas de OpenFoodFacts
- [ ] Webhooks para actualizaciones de productos
- [ ] Sistema de notificaciones push
- [ ] Dashboard de administración
- [ ] Métricas con Prometheus

## 🤝 Contribuir

1. Fork el proyecto
2. Crea una rama para tu feature (`git checkout -b feature/AmazingFeature`)
3. Commit tus cambios (`git commit -m 'Add some AmazingFeature'`)
4. Push a la rama (`git push origin feature/AmazingFeature`)
5. Abre un Pull Request

## 📝 Licencia

Este proyecto es privado y está protegido por derechos de autor.

## 👨‍💻 Autor

**Aleco121**
- GitHub: [@Aleco-121](https://github.com/Aleco-121)

## 🙏 Agradecimientos

- [OpenFoodFacts](https://world.openfoodfacts.org/) por la base de datos de productos
- [Google Gemini](https://ai.google.dev/) por la IA generativa
- [Supabase](https://supabase.com/) por la base de datos cloud
- [FastAPI](https://fastapi.tiangolo.com/) por el framework

---

**Última actualización**: 2026-02-03
