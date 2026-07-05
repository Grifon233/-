#!/bin/bash
# Copy uploaded files to correct locations

# Copy bot handler
cp /root/uploads/restart_admin_commands.py /root/master-booking/architect/handlers/admin_commands.py

# Restart bot service
sudo systemctl restart master-booking-bot

# Copy static files from uploads to static directory
cp /root/uploads/deploy_*.js /var/www/master-booking/static/assets/ 2>/dev/null
cp /root/uploads/deploy_*.css /var/www/master-booking/static/assets/ 2>/dev/null
cp /root/uploads/deploy_*.html /var/www/master-booking/static/ 2>/dev/null

# Restart API to pick up new endpoints
sudo systemctl restart master-booking-api

echo "Done!"
