@echo off
SETLOCAL EnableDelayedExpansion

REM ==========================================
REM   Minecraft 1.8.8 Verify Plugin Compiler
REM   Version: 2.0
REM   For Java 8 and Maven 3.9.11
REM ==========================================

REM Check if running from correct directory
if not exist "src\main\java\com\msga\verify\VerifyPlugin.java" (
    echo [ERROR] VerifyPlugin.java not found!
    echo Please run this script from the project root directory.
    echo Expected: src\main\java\com\msga\verify\VerifyPlugin.java
    pause
    exit /b 1
)

if not exist "pom.xml" (
    echo [ERROR] pom.xml not found!
    echo Please run this script from the project root directory.
    pause
    exit /b 1
)

title Minecraft 1.8.8 Plugin Compiler - VerifyPlugin

echo ==========================================
echo   Minecraft 1.8.8 Verify Plugin Compiler
echo   by MSGA, Voltarian Technologies
echo ==========================================
echo.

REM Set portable tool paths (if available)
SET PORTABLE_MAVEN=%CD%\apache-maven-3.9.11
SET PORTABLE_JAVA=%CD%\jdk8u472-b08

REM Check for portable tools first
SET USING_PORTABLE=0
SET JAVA_FOUND=0
SET MAVEN_FOUND=0

echo [INFO] Checking for portable tools...
echo.

REM Check for portable Java
if exist "%PORTABLE_JAVA%\bin\java.exe" (
    echo [INFO] Found portable Java 8 at: %PORTABLE_JAVA%
    SET JAVA_HOME=%PORTABLE_JAVA%
    SET USING_PORTABLE=1
    SET JAVA_FOUND=1
) else (
    echo [INFO] Portable Java not found, checking system PATH...
)

REM Check for portable Maven
if exist "%PORTABLE_MAVEN%\bin\mvn.cmd" (
    echo [INFO] Found portable Maven at: %PORTABLE_MAVEN%
    SET MAVEN_HOME=%PORTABLE_MAVEN%
    SET USING_PORTABLE=1
    SET MAVEN_FOUND=1
) else (
    echo [INFO] Portable Maven not found, checking system PATH...
)
echo.

REM If portable tools not found, check system PATH
if %JAVA_FOUND% EQU 0 (
    where java >nul 2>nul
    if %ERRORLEVEL% EQU 0 (
        echo [INFO] Found Java in system PATH
        SET JAVA_FOUND=1
        REM Try to find JAVA_HOME from system
        for /f "tokens=*" %%i in ('java -XshowSettings:properties -version 2^>^&1 ^| find "java.home"') do (
            set "JAVA_LINE=%%i"
            set "JAVA_HOME=!JAVA_LINE:*java.home =!"
            set "JAVA_HOME=!JAVA_HOME:~0,-1!"
        )
    ) else (
        echo [ERROR] Java not found!
        echo Please install Java 8 JDK from:
        echo https://adoptium.net/temurin/releases/?version=8
        echo Or extract jdk8u472-b08 to this directory
        pause
        exit /b 1
    )
)

if %MAVEN_FOUND% EQU 0 (
    where mvn >nul 2>nul
    if %ERRORLEVEL% EQU 0 (
        echo [INFO] Found Maven in system PATH
        SET MAVEN_FOUND=1
        REM Try to find MAVEN_HOME from system
        for /f "tokens=*" %%i in ('mvn -version ^| find "Maven home:"') do (
            set "MAVEN_LINE=%%i"
            set "MAVEN_HOME=!MAVEN_LINE:*Maven home: =!"
        )
    ) else (
        echo [ERROR] Maven not found!
        echo Please install Maven from:
        echo https://maven.apache.org/download.cgi
        echo Or extract apache-maven-3.9.11 to this directory
        echo.
        echo After installing, add Maven to your system PATH.
        pause
        exit /b 1
    )
)

REM Update PATH with found tools
if defined JAVA_HOME (
    SET PATH=%JAVA_HOME%\bin;%PATH%
)

if defined MAVEN_HOME (
    SET PATH=%MAVEN_HOME%\bin;%PATH%
)

REM Check Java version
echo [INFO] Checking Java version...
java -version 2>&1 | findstr /i "version" >nul && (
    for /f "tokens=*" %%i in ('java -version 2^>^&1 ^| findstr /i "version"') do (
        set "JAVA_VERSION=%%i"
    )
    echo [INFO] Java Version: !JAVA_VERSION!
)

java -version 2>&1 | findstr /i "1.8" >nul
if %ERRORLEVEL% neq 0 (
    echo [WARNING] Not using Java 8. Minecraft 1.8.8 requires Java 8.
    echo [WARNING] Compilation may fail or plugin may not work correctly.
    echo.
    echo Press any key to continue with current Java version...
    pause >nul
)
echo.

REM Display compilation info
echo [INFO] Project: VerifyPlugin
echo [INFO] Minecraft: 1.8.8
echo [INFO] Target Java: 1.8
echo [INFO] Using portable tools: %USING_PORTABLE%
echo.

echo [INFO] Starting compilation process...
echo ==========================================
echo.

REM Clean previous builds
echo [STEP 1] Cleaning previous builds...
call mvn clean --quiet
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Failed to clean project!
    goto :error
)

REM Download dependencies
echo [STEP 2] Downloading dependencies...
call mvn dependency:resolve --quiet
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Failed to download dependencies!
    goto :error
)

REM Compile the project
echo [STEP 3] Compiling plugin...
echo.
call mvn compile
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Compilation failed!
    goto :error
)

REM Package the plugin
echo [STEP 4] Packaging plugin...
echo.
call mvn package -DskipTests
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Packaging failed!
    goto :error
)

REM Success
echo.
echo ==========================================
echo [SUCCESS] Plugin compiled successfully!
echo ==========================================
echo.
echo [INFO] Files generated:
echo.
dir target\*.jar /b
echo.
echo [INFO] Main JAR: target\VerifyPlugin-1.0.0.jar
echo.
echo [INFO] Plugin Details:
echo   - Name: VerifyPlugin
echo   - Version: 1.0.0
echo   - Minecraft: 1.8.8
echo   - Size: 
for %%F in (target\VerifyPlugin-1.0.0.jar) do (
    for /f %%S in ('%%~zF') do (
        set /a SIZE_KB=%%S/1024
        echo   - Size: !SIZE_KB! KB
    )
)
echo.
echo [INFO] Next steps:
echo   1. Copy the JAR to your server's plugins folder
echo   2. Restart your server
echo   3. Configure plugin in plugins/VerifyPlugin/config.yml
echo.
echo [INFO] Configuration files created:
echo   - plugins/VerifyPlugin/config.yml (on first run)
echo   - plugins/VerifyPlugin/verification_codes.json
echo   - plugins/VerifyPlugin/verification_log.txt
echo.
echo ==========================================
echo [INFO] Compilation completed successfully!
echo ==========================================
goto :end

:error
echo.
echo ==========================================
echo [ERROR] Compilation failed!
echo.
echo [TROUBLESHOOTING]
echo 1. Check your internet connection
echo 2. Verify Java 8 is installed
echo 3. Ensure Maven is installed and in PATH
echo 4. Check pom.xml for errors
echo 5. Clean project: mvn clean
echo.
echo [INFO] Full build log: target\maven.log
echo ==========================================

:end
echo.
echo Press any key to exit...
pause >nul
exit /b