# How to Set Up a Free AWS Windows VPS (From a Mac)

This guide walks you through setting up a free Windows VPS on Amazon Web Services (AWS) and connecting to it from your Mac. 

## Phase 1: Launching the Free Server

1. **Create an AWS Account**
   - Go to [aws.amazon.com](https://aws.amazon.com/) and create a free account. You will need a credit card, but you will not be charged as long as you stay within the Free Tier limits.

2. **Go to the EC2 Dashboard**
   - Once logged into the AWS Management Console, search for **"EC2"** in the top search bar and click it. (EC2 is Amazon's name for virtual servers).

3. **Launch Instance**
   - Click the orange **"Launch instance"** button.
   - **Name:** Give your server a name (e.g., `Mumo-Trading-Bot`).
   - **OS Images (AMI):** Search for "Windows" and select **Microsoft Windows Server 2022 Base**. 
     - *Crucial:* Ensure it has the "**Free tier eligible**" badge under it.
   - **Instance Type:** Select **t2.micro** (or `t3.micro` depending on your region). It should say "Free tier eligible".

4. **Create a Key Pair (Important!)**
   - Under "Key pair (login)", click **"Create new key pair"**.
   - Name it `trading-bot-key`.
   - Key pair type: **RSA**
   - Private key file format: **.pem**
   - Click Create. *This will download a `.pem` file to your Mac. Keep it safe! You need this to get your Windows password.*

5. **Network Settings**
   - Under "Network settings", ensure **"Allow RDP traffic from Anywhere"** is checked. (This allows you to remote into the server).

6. **Storage**
   - Leave it at the default **30 GiB** of `gp2` or `gp3` storage (this is the maximum free tier limit).

7. **Launch!**
   - Click the orange **"Launch instance"** button at the bottom right.

---

## Phase 2: Connecting from your Mac

Windows servers use a protocol called RDP (Remote Desktop Protocol). Macs don't have this built-in, so you need a free app from Microsoft.

1. **Download Microsoft Remote Desktop**
   - Open the **Mac App Store** and search for **"Microsoft Remote Desktop"** (the official app by Microsoft). Download and install it.

2. **Get your Windows Password**
   - Go back to your AWS EC2 Dashboard and click on **"Instances"**.
   - Wait until your new instance's "Instance State" says **Running** and "Status Check" says **2/2 passed** (this takes about 5 minutes).
   - Right-click your instance, select **Security**, then click **Get Windows password**.
   - Click **"Upload private key file"** and select the `.pem` file you downloaded earlier.
   - Click **Decrypt Password**. 
   - AWS will now show you your **Public IP Address**, **Username** (usually `Administrator`), and your decrypted **Password**. Copy these down!

3. **Connect via RDP**
   - Open the **Microsoft Remote Desktop** app on your Mac.
   - Click the **"+"** button at the top and select **"Add PC"**.
   - **PC name:** Paste your AWS **Public IP Address** here.
   - Click **Add**.
   - Double-click the new PC icon that appears in the app.
   - It will ask for credentials. Enter the Username (`Administrator`) and the Password you decrypted from AWS.
   - If you get a certificate warning, click **"Continue"**.

🎉 **You are now logged into your Windows VPS!** It will look like a standard Windows desktop running inside a window on your Mac.

---

## Phase 3: Moving the Bot to the Server

Now that you're on the Windows VPS, follow the **[VPS_DEPLOYMENT_GUIDE.md](file:///Users/kiplaa/Desktop/Projects/mumo-syntax-capital/VPS_DEPLOYMENT_GUIDE.md)**:

1. Copy-paste your zipped project folder directly from your Mac desktop into the Windows Remote Desktop window.
2. Open Microsoft Edge on the VPS and download/install **Python 3.10+**.
3. Install **MetaTrader 5** from your broker's website.
4. Run `start_vps.bat`!
