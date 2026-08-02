# user-auth Specification

## Purpose

Autenticación de la frontera F1 (browser ↔ backend): admin único con token de sesión. Cierra V1 y V6 (acceso sin autenticación y credenciales hardcodeadas).

## Requirements

### Requirement: Login de admin

The system MUST authenticate the single admin user using credentials from configuration (env/.env, con defaults documentados y sin secretos commiteados). On failure, the system MUST respond 401 sin revelar qué campo (usuario o contraseña) falló.

#### Scenario: Login exitoso

- GIVEN credenciales válidas en la configuración
- WHEN el admin envía usuario y contraseña correctos a `/api/login`
- THEN el sistema responde 200 con un token de sesión

#### Scenario: Login fallido

- GIVEN credenciales inválidas
- WHEN el admin envía credenciales incorrectas
- THEN el sistema responde 401 sin indicar qué campo falló

### Requirement: Token de sesión

The system MUST issue a session token on successful login. The token MUST be required for all protected endpoints y MUST ser invalidado en logout o al reiniciar el servidor.

#### Scenario: Acceso con token válido

- GIVEN un login exitoso
- WHEN una petición a un endpoint protegido incluye el token
- THEN el sistema procesa la petición

#### Scenario: Token ausente o desconocido

- GIVEN un token ausente, desconocido o ya invalidado
- WHEN se accede a un endpoint protegido
- THEN el sistema responde 401

### Requirement: Logout

The system MUST invalidar el token de sesión al ejecutar logout.

#### Scenario: Logout

- GIVEN una sesión activa
- WHEN el admin ejecuta logout
- THEN el token deja de ser válido y las peticiones posteriores reciben 401
