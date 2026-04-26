import { ethers } from 'ethers';
import { createZGComputeNetworkBroker } from '@0glabs/0g-serving-broker';
import * as fs from 'fs';
import 'dotenv/config';

async function discover(): Promise<void> {
  if (!process.env.PRIVATE_KEY) throw new Error('PRIVATE_KEY not set in .env');
  if (!process.env.RPC_URL) throw new Error('RPC_URL not set in .env');

  const provider = new ethers.JsonRpcProvider(process.env.RPC_URL);
  const wallet = new ethers.Wallet(process.env.PRIVATE_KEY, provider);
  const broker = await createZGComputeNetworkBroker(wallet as any);

  console.log('Listing all services...\n');
  const services = await broker.inference.listService();

  // Services are tuple arrays:
  // s[0] = providerAddress, s[1] = serviceType, s[6] = model, s[10] = teeVerified
  const chatbotServices = services.filter(
    (s: any) => s[1] === 'chatbot' || s[1] === 'chat'
  );

  console.log(`Found ${chatbotServices.length} chatbot provider(s):\n`);

  const providers = chatbotServices.map((s: any) => ({
    address: s[0],
    type: s[1],
    model: s[6],
    teeVerified: s[10],
  }));

  for (const p of providers) {
    console.log(`  Address: ${p.address}`);
    console.log(`  Model:   ${p.model}`);
    console.log(`  TEE:     ${p.teeVerified ? 'verified' : 'unverified'}`);
    console.log();
  }

  fs.writeFileSync('providers.json', JSON.stringify(providers, null, 2));
  console.log('Saved to providers.json');
}

discover().catch((err) => {
  console.error('Error:', err.message);
  process.exit(1);
});
