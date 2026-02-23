#!/bin/bash

echo "========================================="
echo " SmartFlashCard - macOS Build Script"
echo "========================================="
echo ""

# Activate Virtual Environment to ensure we use the correct Python instance
if [ -d "venv" ]; then
    echo "Activating virtual environment..."
    source venv/bin/activate
else
    echo "Warning: 'venv' directory not found. Proceeding with global python..."
fi

echo "Installing requirements..."
pip install -r requirements.txt
pip install pyinstaller
echo ""
echo "Starting PyInstaller build process..."
pyinstaller --clean build_scripts/build_mac.spec
echo ""
echo "========================================="
echo "Build Complete!"
echo "Your .app file is located in the 'dist' folder."
echo "========================================="
