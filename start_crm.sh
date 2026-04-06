#!/bin/bash
# Wrapper script for launchd to start CRM portal with venv
cd "/Users/daksh/Desktop/code/Content Project/icp-scraper"
source venv/bin/activate
exec python run_crm.py
