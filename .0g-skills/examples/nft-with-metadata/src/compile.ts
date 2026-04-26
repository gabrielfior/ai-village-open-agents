import * as fs from 'fs';
import * as path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

async function compile(): Promise<void> {
  // Dynamic import for solc (devDependency)
  const solc = (await import('solc')).default;

  const contractPath = path.resolve(__dirname, '../contracts/StorageRegistry.sol');
  const source = fs.readFileSync(contractPath, 'utf-8');

  const input = {
    language: 'Solidity',
    sources: { 'StorageRegistry.sol': { content: source } },
    settings: {
      evmVersion: 'cancun', // REQUIRED for 0G Chain
      optimizer: { enabled: true, runs: 200 },
      outputSelection: { '*': { '*': ['abi', 'evm.bytecode.object'] } },
    },
  };

  const output = JSON.parse(solc.compile(JSON.stringify(input)));

  if (output.errors?.some((e: any) => e.severity === 'error')) {
    console.error('Compilation errors:');
    output.errors.forEach((e: any) => console.error(e.formattedMessage));
    process.exit(1);
  }

  const contract = output.contracts['StorageRegistry.sol']['StorageRegistry'];
  const artifact = {
    contractName: 'StorageRegistry',
    abi: contract.abi,
    bytecode: '0x' + contract.evm.bytecode.object,
    compiler: {
      version: solc.version(),
      settings: { evmVersion: 'cancun', optimizer: { enabled: true, runs: 200 } },
    },
  };

  const artifactPath = path.resolve(__dirname, '../artifacts/StorageRegistry.json');
  fs.writeFileSync(artifactPath, JSON.stringify(artifact, null, 2));
  console.log(`Compiled StorageRegistry → ${artifactPath}`);
}

compile().catch((err) => {
  console.error('Error:', err.message);
  process.exit(1);
});
