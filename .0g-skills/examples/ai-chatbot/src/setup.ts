import { ethers } from 'ethers';
import { createZGComputeNetworkBroker } from '@0glabs/0g-serving-broker';
import 'dotenv/config';

async function setup(providerAddress: string): Promise<void> {
  if (!process.env.PRIVATE_KEY) throw new Error('PRIVATE_KEY not set in .env');
  if (!process.env.RPC_URL) throw new Error('RPC_URL not set in .env');

  const provider = new ethers.JsonRpcProvider(process.env.RPC_URL);
  const wallet = new ethers.Wallet(process.env.PRIVATE_KEY, provider);
  const broker = await createZGComputeNetworkBroker(wallet as any);

  // Step 1: Deposit to main account (depositFund takes a number in 0G)
  const depositAmount = 0.05;
  console.log(`Depositing ${depositAmount} 0G to main account...`);
  await broker.ledger.depositFund(depositAmount);

  // Check balance — getLedger returns tuple: [1]=total, [2]=available
  const ledger = await broker.ledger.getLedger();
  console.log(`Main account balance: ${ethers.formatEther(ledger[2])} 0G available`);

  // Step 2: Transfer to provider sub-account
  // transferFund(provider, serviceType, amount)
  const transferAmount = ethers.parseEther('0.01');
  console.log(`\nTransferring 0.01 0G to provider ${providerAddress}...`);
  await broker.ledger.transferFund(providerAddress, 'inference', transferAmount);

  // Step 3: Acknowledge provider (required before first use)
  console.log('Acknowledging provider signer...');
  await broker.inference.acknowledgeProviderSigner(providerAddress);

  console.log('\nSetup complete! You can now chat with this provider.');
}

// CLI entrypoint
const providerAddress = process.argv[2];
if (!providerAddress) {
  console.error('Usage: npx tsx src/setup.ts <provider-address>');
  process.exit(1);
}

setup(providerAddress).catch((err) => {
  console.error('Error:', err.message);
  process.exit(1);
});
