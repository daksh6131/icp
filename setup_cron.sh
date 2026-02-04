#!/bin/bash
# Setup script for ICP Scraper cron job on macOS
#
# This script sets up a daily cron job to run the ICP scraper at 8am.
# You can also use launchd (macOS native) for more robust scheduling.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_PATH=$(which python3)
LOG_FILE="$SCRIPT_DIR/cron.log"

echo "ICP Scraper Cron Setup"
echo "======================"
echo ""
echo "Script directory: $SCRIPT_DIR"
echo "Python path: $PYTHON_PATH"
echo ""

# Check if .env exists
if [ ! -f "$SCRIPT_DIR/.env" ]; then
    echo "WARNING: .env file not found!"
    echo "Please copy .env.example to .env and configure it:"
    echo "  cp $SCRIPT_DIR/.env.example $SCRIPT_DIR/.env"
    echo ""
fi

# Check if credentials.json exists
if [ ! -f "$SCRIPT_DIR/credentials.json" ]; then
    echo "WARNING: credentials.json not found!"
    echo "Please follow the Google Sheets setup instructions in the README."
    echo ""
fi

echo "Choose setup method:"
echo "  1) Cron job (simpler)"
echo "  2) launchd (macOS native, more robust)"
echo ""
read -p "Enter choice (1 or 2): " choice

if [ "$choice" = "1" ]; then
    # Setup cron job
    CRON_LINE="0 8 * * * cd $SCRIPT_DIR && $PYTHON_PATH main.py >> $LOG_FILE 2>&1"

    # Check if cron job already exists
    if crontab -l 2>/dev/null | grep -q "icp-scraper"; then
        echo "Cron job already exists. Updating..."
        crontab -l | grep -v "icp-scraper" | crontab -
    fi

    # Add new cron job
    (crontab -l 2>/dev/null; echo "# icp-scraper daily run"; echo "$CRON_LINE") | crontab -

    echo ""
    echo "Cron job installed! The scraper will run daily at 8:00 AM."
    echo "Logs will be written to: $LOG_FILE"
    echo ""
    echo "To view current cron jobs: crontab -l"
    echo "To remove: crontab -e (and delete the icp-scraper lines)"

elif [ "$choice" = "2" ]; then
    # Setup launchd
    PLIST_FILE="$HOME/Library/LaunchAgents/com.icp-scraper.plist"

    cat > "$PLIST_FILE" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.icp-scraper</string>
    <key>ProgramArguments</key>
    <array>
        <string>$PYTHON_PATH</string>
        <string>$SCRIPT_DIR/main.py</string>
    </array>
    <key>WorkingDirectory</key>
    <string>$SCRIPT_DIR</string>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>8</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>$SCRIPT_DIR/launchd.log</string>
    <key>StandardErrorPath</key>
    <string>$SCRIPT_DIR/launchd.error.log</string>
    <key>RunAtLoad</key>
    <false/>
</dict>
</plist>
EOF

    # Load the launchd job
    launchctl unload "$PLIST_FILE" 2>/dev/null
    launchctl load "$PLIST_FILE"

    echo ""
    echo "launchd job installed! The scraper will run daily at 8:00 AM."
    echo "Plist file: $PLIST_FILE"
    echo "Logs: $SCRIPT_DIR/launchd.log"
    echo ""
    echo "To run manually: launchctl start com.icp-scraper"
    echo "To stop: launchctl stop com.icp-scraper"
    echo "To uninstall: launchctl unload $PLIST_FILE && rm $PLIST_FILE"
else
    echo "Invalid choice. Exiting."
    exit 1
fi

echo ""
echo "Setup complete!"
echo ""
echo "To test the scraper manually:"
echo "  cd $SCRIPT_DIR"
echo "  python3 main.py"
