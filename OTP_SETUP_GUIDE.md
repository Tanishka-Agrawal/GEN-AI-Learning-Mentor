# OTP System Setup Guide

## Overview
The GenAI Learning Mentor includes a complete OTP (One-Time Password) verification system for user registration. The system supports both Email OTP and SMS OTP verification methods.

## Current Implementation Status
✅ **Fully Implemented** - The OTP system is complete and includes:
- `/api/start-register` - Initiates registration and sends OTP
- `/api/verify-otp` - Verifies the OTP and creates the account
- `/api/resend-otp` - Resends OTP with 30-second cooldown
- Email OTP via Gmail SMTP (or any SMTP server)
- SMS OTP via Twilio (international) or Fast2SMS (India)
- Development mode for testing without credentials
- 5-minute OTP expiry
- Maximum 3 incorrect attempts
- Session-based temporary storage
- Comprehensive error handling and logging

## How It Works

### Registration Flow
1. User fills registration form (username, email, phone, password)
2. User selects verification method (Email OTP or SMS OTP)
3. System validates input and checks uniqueness
4. System generates 6-digit random OTP
5. System sends OTP via selected method
6. OTP modal appears for user to enter code
7. User enters OTP and system verifies it
8. If correct, account is created and user can login
9. If incorrect, user gets 3 attempts before registration is locked

### Development Mode (Default)
When SMTP/SMS credentials are not configured, the system runs in **development mode**:
- OTP is printed to the server console
- OTP is also shown in the UI (dev mode indicator)
- No actual email/SMS is sent
- Perfect for testing without API credentials

### Production Mode
When credentials are configured:
- Real emails are sent via SMTP
- Real SMS are sent via Twilio or Fast2SMS
- OTP is not shown in UI
- Full security and verification

## Configuration

### Step 1: Copy Environment Template
```bash
cp .env.template .env
```

### Step 2: Configure Required Variables
Edit `.env` file and set these required variables:

```bash
# Required for AI features
GEMINI_API_KEY=your_gemini_api_key_here
FLASK_SECRET_KEY=your_secret_key_here

# OTP Mode (true = dev mode, false = production mode)
OTP_DEV_MODE=true
```

### Step 3: Configure Email OTP (Optional but Recommended)
For production email OTP, configure SMTP settings:

```bash
# Gmail Example (Recommended)
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=your-email@gmail.com
SMTP_PASSWORD=your-app-password
```

**Important for Gmail:**
1. Go to https://myaccount.google.com/apppasswords
2. Generate an App Password (not your regular password)
3. Use the App Password as SMTP_PASSWORD
4. Enable 2-factor authentication on your Google account first

**Alternative SMTP Servers:**
- Outlook: `smtp-mail.outlook.com:587`
- Yahoo: `smtp.mail.yahoo.com:587`
- SendGrid: `smtp.sendgrid.net:587`

### Step 4: Configure SMS OTP (Optional)
Choose one of the following SMS providers:

#### Option A: Twilio (International - Recommended)
```bash
TWILIO_ACCOUNT_SID=your_twilio_account_sid
TWILIO_AUTH_TOKEN=your_twilio_auth_token
TWILIO_FROM_NUMBER=+1234567890
```

Get credentials from: https://www.twilio.com/console

#### Option B: Fast2SMS (India Only)
```bash
FAST2SMS_API_KEY=your_fast2sms_api_key
```

Get API key from: https://www.fast2sms.com/

## Testing the OTP System

### Test in Development Mode (No Credentials Needed)
1. Set `OTP_DEV_MODE=true` in `.env`
2. Start the Flask application: `python app.py`
3. Navigate to `/auth` and click Register tab
4. Fill in registration details
5. Select Email OTP or SMS OTP
6. Click "Create Account"
7. Check the server console - you'll see: `[MAIL OTP DEV] SMTP not configured — simulated delivery to {email}. OTP: {code}`
8. In the OTP modal, you'll also see the dev mode code displayed
9. Enter the code and verify

### Test in Production Mode (With Credentials)
1. Configure SMTP or SMS credentials in `.env`
2. Set `OTP_DEV_MODE=false` in `.env`
3. Start the Flask application
4. Register a new account
5. Check your email or phone for the OTP
6. Enter the code to verify

## Troubleshooting

### Issue: "Failed to deliver verification code"
**Solution:** Check console logs for specific error messages:
- `[SMTP ERROR]` - Email configuration issue
- `[TWILIO ERROR]` - Twilio API issue  
- `[FAST2SMS ERROR]` - Fast2SMS API issue

### Issue: OTP not received in email
**Solutions:**
1. Check spam/junk folder
2. Verify SMTP credentials are correct
3. For Gmail, ensure you're using an App Password (not regular password)
4. Check if firewall is blocking SMTP ports (587, 465)

### Issue: OTP not received via SMS
**Solutions:**
1. Verify phone number format (include country code)
2. Check Twilio/Fast2SMS account balance
3. Verify API credentials are correct
4. For Fast2SMS, ensure phone number is 10 digits (Indian numbers)

### Issue: "Registration session expired"
**Solution:** The registration session times out after 5 minutes. Start the registration process again.

### Issue: "Maximum incorrect attempts exceeded"
**Solution:** After 3 incorrect OTP attempts, the registration is locked. Start the registration process again.

## API Endpoints

### POST /api/start-register
Initiates registration and sends OTP.

**Request:**
```json
{
  "username": "testuser",
  "email": "test@example.com",
  "phone": "+919876543210",
  "password": "SecurePass123!",
  "verification_method": "email"  // or "sms"
}
```

**Response (Success):**
```json
{
  "success": true,
  "message": "Verification code sent successfully.",
  "target": "test@example.com",
  "method": "email",
  "dev_otp": "123456"  // Only in dev mode
}
```

**Response (Error):**
```json
{
  "error": "Error message here"
}
```

### POST /api/verify-otp
Verifies the OTP and creates the account.

**Request:**
```json
{
  "otp": "123456"
}
```

**Response (Success):**
```json
{
  "success": true,
  "message": "Account verified and created successfully! You can sign in now."
}
```

**Response (Error):**
```json
{
  "error": "Incorrect code. 2 attempt(s) remaining."
}
```

### POST /api/resend-otp
Resends the OTP with 30-second cooldown.

**Request:** (empty body)

**Response (Success):**
```json
{
  "success": true,
  "message": "A new verification code has been sent to your email.",
  "target": "test@example.com",
  "method": "email",
  "dev_otp": "789012"  // Only in dev mode
}
```

## Security Features

1. **5-minute OTP expiry** - Codes expire automatically
2. **3 attempt limit** - Prevents brute force attacks
3. **Session-based storage** - OTPs are stored in session, not database
4. **Dev mode indicator** - Clear visual indication in development
5. **Input validation** - All fields are validated before OTP generation
6. **Uniqueness checks** - Username, email, and phone must be unique
7. **Password strength** - Enforces strong password requirements

## Console Logging

The system provides detailed console logging for debugging:

```
[MAIL OTP DEV] SMTP not configured — simulated delivery to test@example.com. OTP: 123456
[SMTP SUCCESS] Email sent successfully to test@example.com
[SMTP ERROR] Failed to send email to test@example.com: Authentication failed
[TWILIO SUCCESS] SMS sent successfully to +919876543210
[SMS OTP DEV] SMS not configured — simulated delivery to +919876543210. OTP: 123456
```

## Dependencies

All required dependencies are in `requirements.txt`:
- Flask (web framework)
- python-dotenv (environment variables)
- Werkzeug (password hashing)

No additional dependencies needed for OTP functionality.

## Support

For issues or questions:
1. Check the console logs for detailed error messages
2. Verify your `.env` configuration
3. Ensure all required credentials are set correctly
4. Test in dev mode first before configuring production credentials
