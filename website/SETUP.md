# Zil Website Setup

## Notify Me Form Setup

The website includes a "Notify me" form that collects visitor interest. Here's how to set it up:

### 1. Create a Resend Account

1. Go to [resend.com](https://resend.com)
2. Sign up for a free account (100 emails/day free tier)
3. Verify your email address

### 2. Get Your API Key

1. Go to [API Keys](https://resend.com/api-keys)
2. Click "Create API Key"
3. Give it a name like "Zil Website"
4. Copy the API key (starts with `re_`)

### 3. Set Up Environment Variables

#### Local Development

1. Copy `.env.example` to `.env.local`:
   ```bash
   cp .env.example .env.local
   ```

2. Edit `.env.local` and add your keys:
   ```
   RESEND_API_KEY=re_your_actual_key_here
   NOTIFICATION_EMAIL=hello@fluentdata.ai
   ```

#### Vercel Deployment

1. Go to your Vercel project settings
2. Navigate to "Environment Variables"
3. Add these variables:
   - `RESEND_API_KEY` = your Resend API key
   - `NOTIFICATION_EMAIL` = hello@fluentdata.ai

### 4. Verify Domain (Optional but Recommended)

For production, verify your domain in Resend:

1. Go to [Domains](https://resend.com/domains) in Resend
2. Click "Add Domain"
3. Add `fluentdata.ai`
4. Follow DNS setup instructions
5. Once verified, update the API route to use:
   ```typescript
   from: 'Zil <noreply@fluentdata.ai>'
   ```

### 5. Test the Form

1. Run the dev server: `pnpm dev`
2. Navigate to the form section
3. Fill out and submit
4. Check your `NOTIFICATION_EMAIL` inbox

## Form Features

- Collects: Name, Email, Company, Title
- Client-side validation
- Server-side validation
- Email notification to FluentData
- Success/error feedback
- Fully styled to match Zil design system

## Troubleshooting

**Form not submitting?**
- Check browser console for errors
- Verify environment variables are set
- Check Vercel function logs

**Not receiving emails?**
- Verify Resend API key is correct
- Check Resend dashboard for delivery logs
- Verify `NOTIFICATION_EMAIL` is correct

**Rate limits?**
- Free tier: 100 emails/day
- Upgrade Resend plan if needed
