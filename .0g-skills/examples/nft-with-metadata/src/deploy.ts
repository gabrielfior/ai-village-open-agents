import { ethers } from 'ethers';
import * as fs from 'fs';
import * as path from 'path';
import { fileURLToPath } from 'url';
import 'dotenv/config';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

async function deploy(): Promise<string> {
  if (!process.env.PRIVATE_KEY) throw new Error('PRIVATE_KEY not set in .env');
  if (!process.env.RPC_URL) throw new Error('RPC_URL not set in .env');

  const provider = new ethers.JsonRpcProvider(process.env.RPC_URL);
  const wallet = new ethers.Wallet(process.env.PRIVATE_KEY, provider);

  console.log(`Deploying from: ${wallet.address}`);
  const balance = await provider.getBalance(wallet.address);
  console.log(`Balance: ${ethers.formatEther(balance)} 0G`);

  const artifactPath = path.resolve(__dirname, '../artifacts/StorageRegistry.json');
  const artifact = JSON.parse(fs.readFileSync(artifactPath, 'utf-8'));

  const factory = new ethers.ContractFactory(artifact.abi, artifact.bytecode, wallet);
  console.log('Deploying StorageRegistry...');

  const contract = await factory.deploy();
  await contract.waitForDeployment();

  const address = await contract.getAddress();
  console.log(`\nRegistry deployed at: ${address}`);
  console.log('Add this to REGISTRY_ADDRESS in your .env file');

  return address;
}

deploy().catch((err) => {
  console.error('Error:', err.message);
  process.exit(1);
});
