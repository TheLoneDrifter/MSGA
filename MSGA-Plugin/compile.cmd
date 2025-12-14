@echo off
SET MAVEN_HOME=%CD%\apache-maven-3.9.11
SET JAVA_HOME=%CD%\jdk8u472-b08
SET PATH=%PATH%;%MAVEN_HOME%\bin;%JAVA_HOME%\bin;
title Minecraft Plugin Compiler
echo ==========================================
echo   Minecraft 1.8.8 Verify Plugin Compiler
echo ==========================================
echo.

REM Check for Java
where java >nul 2>nul
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Java not found in PATH!
    echo Please install Java 8 JDK from:
    echo https://adoptium.net/temurin/releases/?version=8
    pause
    exit /b 1
)

REM Check Java version
java -version 2>&1 | findstr /i "1.8" >nul
if %ERRORLEVEL% neq 0 (
    echo [WARNING] Not using Java 8. Minecraft 1.8.8 requires Java 8.
    echo.
)

REM Check for Maven
where mvn >nul 2>nul
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Maven not found in PATH!
    echo Please install Maven from:
    echo https://maven.apache.org/download.cgi
    echo.
    echo After installing, add Maven to your system PATH.
    pause
    exit /b 1
)

echo [INFO] Checking project structure...
if not exist "src\main\java\com\msga\verify\VerifyPlugin.java" (
    echo [ERROR] VerifyPlugin.java not found!
    echo Expected at: src\main\java\com\msga\verify\VerifyPlugin.java
    pause
    exit /b 1
)

if not exist "pom.xml" (
    echo [ERROR] pom.xml not found!
    pause
    exit /b 1
)

echo [INFO] Cleaning previous builds...
call mvn clean >nul 2>nul

echo [INFO] Compiling plugin...
echo ==========================================
call mvn clean package

if %ERRORLEVEL% equ 0 (
    echo.
    echo ==========================================
    echo [SUCCESS] Plugin compiled successfully!
    echo.
    echo Your JAR file is located at:
    echo   target\VerifyPlugin-1.0.0.jar
    echo.
    echo Copy this file to your server's plugins folder.
    echo ==========================================
) else (
    echo.
    echo ==========================================
    echo [ERROR] Compilation failed!
    echo Check the error messages above.
    echo ==========================================
)

pause